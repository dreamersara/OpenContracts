"""
Tests for materialized view management.
"""

from django.contrib.auth import get_user_model
from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase

User = get_user_model()


class MaterializedViewTestCase(BaseFixtureTestCase):
    """
    Test that materialized views are properly created and function correctly.
    """

    def test_materialized_views_exist(self):
        """Test that materialized views are created after migration"""

        with connection.cursor() as cursor:
            # Check if materialized views exist
            cursor.execute(
                """
                SELECT matviewname
                FROM pg_matviews
                WHERE matviewname IN ('annotation_summary_mv', 'annotation_navigation_mv')
                ORDER BY matviewname;
            """
            )

            views = [row[0] for row in cursor.fetchall()]

            self.assertIn(
                "annotation_navigation_mv",
                views,
                "annotation_navigation_mv materialized view not found",
            )
            self.assertIn(
                "annotation_summary_mv",
                views,
                "annotation_summary_mv materialized view not found",
            )

    def test_annotation_summary_mv_content(self):
        """Test that annotation_summary_mv contains correct aggregations"""

        # Create test data
        corpus = Corpus.objects.create(title="Test MV Corpus", creator=self.user)

        label = AnnotationLabel.objects.create(text="MV Test Label", creator=self.user)

        # Create annotations
        annotations = []
        for page in [1, 3, 5, 7]:  # Non-consecutive pages
            for i in range(3):
                annotations.append(
                    Annotation(
                        document=self.doc,
                        corpus=corpus,
                        page=page,
                        annotation_label=label,
                        raw_text=f"MV test annotation {i} on page {page}",
                        creator=self.user,
                        structural=(
                            i == 0
                        ),  # First annotation on each page is structural
                    )
                )

        Annotation.objects.bulk_create(annotations)

        # Refresh materialized view
        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW annotation_summary_mv")

            # Query the materialized view
            cursor.execute(
                """
                SELECT
                    annotation_count,
                    structural_count,
                    user_annotation_count,
                    page_count,
                    pages_with_annotations,
                    first_annotated_page,
                    last_annotated_page
                FROM annotation_summary_mv
                WHERE document_id = %s AND corpus_id = %s
            """,
                [self.doc.id, corpus.id],
            )

            result = cursor.fetchone()

            if result:
                (
                    annotation_count,
                    structural_count,
                    user_annotation_count,
                    page_count,
                    pages_with_annotations,
                    first_annotated_page,
                    last_annotated_page,
                ) = result

                # Verify aggregations
                self.assertEqual(
                    annotation_count, 8
                )  # 4 pages * 2 non-structural per page
                self.assertEqual(structural_count, 4)  # 4 pages * 1 structural per page
                self.assertEqual(
                    user_annotation_count, 8
                )  # All non-structural are user annotations
                self.assertEqual(page_count, 4)
                self.assertEqual(set(pages_with_annotations), {1, 3, 5, 7})
                self.assertEqual(first_annotated_page, 1)
                self.assertEqual(last_annotated_page, 7)
            else:
                self.fail(
                    "No data found in annotation_summary_mv for test document and corpus"
                )

    def test_annotation_navigation_mv_content(self):
        """Test that annotation_navigation_mv contains correct data"""

        # Create test data
        corpus = Corpus.objects.create(title="Nav Test Corpus", creator=self.user)

        label = AnnotationLabel.objects.create(text="Nav Test Label", creator=self.user)

        # Create non-structural annotations
        test_annotation = Annotation.objects.create(
            document=self.doc,
            corpus=corpus,
            page=10,
            annotation_label=label,
            raw_text="Navigation test annotation",
            creator=self.user,
            structural=False,
            bounding_box={"x": 100, "y": 200, "width": 300, "height": 50},
        )

        # Create a structural annotation (should NOT appear in navigation MV)
        Annotation.objects.create(
            document=self.doc,
            corpus=corpus,
            page=10,
            annotation_label=label,
            raw_text="Structural annotation (should not appear)",
            creator=self.user,
            structural=True,
        )

        # Refresh materialized view
        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW annotation_navigation_mv")

            # Query the materialized view
            cursor.execute(
                """
                SELECT id, page, bounding_box
                FROM annotation_navigation_mv
                WHERE document_id = %s AND corpus_id = %s
                ORDER BY id
            """,
                [self.doc.id, corpus.id],
            )

            results = cursor.fetchall()

            # Should only have the non-structural annotation
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0], test_annotation.id)
            self.assertEqual(results[0][1], 10)
            self.assertIsNotNone(results[0][2])  # bounding_box should be present

    def test_materialized_view_indexes(self):
        """Test that materialized views have proper indexes for performance"""

        with connection.cursor() as cursor:
            # Check indexes on annotation_summary_mv
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'annotation_summary_mv'
                ORDER BY indexname;
            """
            )

            summary_indexes = [row[0] for row in cursor.fetchall()]

            self.assertIn(
                "annotation_summary_mv_doc_corpus_uidx",
                summary_indexes,
                "Unique index on annotation_summary_mv not found",
            )
            self.assertIn(
                "annotation_summary_mv_corpus_idx",
                summary_indexes,
                "Corpus index on annotation_summary_mv not found",
            )

            # Check indexes on annotation_navigation_mv
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'annotation_navigation_mv'
                ORDER BY indexname;
            """
            )

            nav_indexes = [row[0] for row in cursor.fetchall()]

            self.assertIn(
                "annotation_navigation_mv_id_uidx",
                nav_indexes,
                "Unique index on annotation_navigation_mv not found",
            )
            self.assertIn(
                "annotation_navigation_mv_doc_corpus_idx",
                nav_indexes,
                "Document-corpus index on annotation_navigation_mv not found",
            )
