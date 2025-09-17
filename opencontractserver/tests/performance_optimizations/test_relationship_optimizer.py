"""
Test RelationshipQueryOptimizer functionality.
"""

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from opencontractserver.annotations.models import (
    Annotation,
    AnnotationLabel,
    Relationship,
)
from opencontractserver.annotations.query_optimizer import RelationshipQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.types.enums import LabelType
from opencontractserver.users.models import User


class RelationshipQueryOptimizerTest(TestCase):
    """Test the RelationshipQueryOptimizer class."""

    def setUp(self):
        """Set up test data."""
        cache.clear()

        # Create test users
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com", password="testpass123"
        )
        self.user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="testpass456"
        )

        # Create test document
        self.doc = Document.objects.create(
            title="Test Document",
            creator=self.user1,
            file_type="application/pdf",
            pdf_file="test.pdf",
        )

        # Create test corpus
        self.corpus = Corpus.objects.create(title="Test Corpus", creator=self.user1)

        # Make document and corpus public to avoid permission gating in tests
        self.doc.is_public = True
        self.doc.save(update_fields=["is_public"])
        self.corpus.is_public = True
        self.corpus.save(update_fields=["is_public"])

        # Create annotation label
        self.ann_label = AnnotationLabel.objects.create(
            text="Test Annotation Label",
            creator=self.user1,
            label_type=LabelType.SPAN_LABEL,
        )

        # Create relationship label (using AnnotationLabel for relationships)
        self.rel_label = AnnotationLabel.objects.create(
            text="Test Relationship",
            creator=self.user1,
            label_type=LabelType.RELATIONSHIP_LABEL,
        )

        # Create annotations
        self.ann1 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.ann_label,
            raw_text="Annotation 1",
            creator=self.user1,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        self.ann2 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=2,
            annotation_label=self.ann_label,
            raw_text="Annotation 2",
            creator=self.user1,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        # Create relationships
        self.rel_public = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=True,
        )
        self.rel_public.source_annotations.set([self.ann1])
        self.rel_public.target_annotations.set([self.ann2])

        self.rel_private = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=False,
        )
        self.rel_private.source_annotations.set([self.ann2])
        self.rel_private.target_annotations.set([self.ann1])

        self.rel_user2 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user2,
            is_public=False,
        )
        self.rel_user2.source_annotations.set([self.ann1])
        self.rel_user2.target_annotations.set([self.ann2])

        # Create an analyzer and two analyses for analysis filtering tests
        from opencontractserver.analyzer.models import Analysis, Analyzer

        self.analyzer = Analyzer.objects.create(
            id="unit-test-analyzer",
            creator=self.user1,
            description="Test Analyzer",
            is_public=True,
            task_name="unit-test-task",
        )
        self.analysis1 = Analysis.objects.create(
            analyzer=self.analyzer,
            creator=self.user1,
            is_public=True,
            analyzed_corpus=self.corpus,
        )
        self.analysis2 = Analysis.objects.create(
            analyzer=self.analyzer,
            creator=self.user1,
            is_public=True,
            analyzed_corpus=self.corpus,
        )

        # Relationships tied to specific analyses
        self.rel_analysis1 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=False,
            analysis=self.analysis1,
        )
        self.rel_analysis1.source_annotations.set([self.ann1])
        self.rel_analysis1.target_annotations.set([self.ann2])

        self.rel_analysis2 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=False,
            analysis=self.analysis2,
        )
        self.rel_analysis2.source_annotations.set([self.ann1])
        self.rel_analysis2.target_annotations.set([self.ann2])

    def test_get_document_relationships_permission_filtering(self):
        """Test that relationship queries respect user permissions."""
        # User1 should see their own relationships (public and private)
        rels_user1 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        self.assertEqual(rels_user1.count(), 2)  # rel_public and rel_private

        # User2 should see public relationships and their own
        rels_user2 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user2,
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        self.assertEqual(rels_user2.count(), 2)  # rel_public and rel_user2

        # Anonymous user should only see public relationships
        rels_anon = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=None,
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        self.assertEqual(rels_anon.count(), 1)  # rel_public only

    def test_superuser_sees_all_relationships(self):
        """Superuser should see all relationships regardless of creator/public flags."""
        admin = User.objects.create_superuser(
            username="superadmin", email="admin@example.com", password="adminpass"
        )

        rels_admin = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=admin,
            corpus_id=self.corpus.id,
            use_cache=False,
        )

        # rel_public, rel_private (user1), rel_user2 (user2) => 3 total
        self.assertEqual(rels_admin.count(), 3)

    def test_page_filtering(self):
        """Test filtering relationships by page."""
        # Get relationships touching page 1
        rels_page1 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            pages=[1],
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        # All relationships touch page 1 (through ann1)
        self.assertEqual(rels_page1.count(), 2)

        # Get relationships touching page 2
        rels_page2 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            pages=[2],
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        # All relationships touch page 2 (through ann2)
        self.assertEqual(rels_page2.count(), 2)

        # Empty pages should return no relationships
        rels_empty = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            pages=[],
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        self.assertEqual(rels_empty.count(), 0)

    def test_page_filtering_multiple_pages_and_no_duplication(self):
        """Filtering by multiple pages returns union of matches without duplicates."""
        # Create a relationship that touches both pages 1 and 2 by linking both annotations
        rel_both = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=True,
        )
        rel_both.source_annotations.set([self.ann1])
        rel_both.target_annotations.set([self.ann2])

        # Query page 1 and 2 together
        rels_pages_1_2 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            pages=[1, 2],
            corpus_id=self.corpus.id,
            use_cache=False,
        )

        # Should include rel_public, rel_private, rel_user2 filtered
        # by user1 perms (public+own => 2), plus rel_both (public) => still 3
        # And no duplicates even though rel_both touches both pages
        ids = list(rels_pages_1_2.values_list("id", flat=True))  # noqa: E501
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(self.rel_public.id, ids)
        self.assertIn(self.rel_private.id, ids)
        self.assertIn(rel_both.id, ids)

    def test_corpus_and_structural_behavior(self):
        """With corpus filter, include structural relationships; with corpus=None, return structural only."""
        # Add a structural relationship (belongs to document, structural=True)
        structural_rel = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=True,
            structural=True,
        )
        structural_rel.source_annotations.set([self.ann1])
        structural_rel.target_annotations.set([self.ann2])

        # Query with corpus filter: expect structural relationship plus corpus-scoped relationships
        rels_with_corpus = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            use_cache=False,
        )
        # rel_public, rel_private, rel_user2 (filtered by user1 perms -> public+own => 2), plus structural (1) => 3
        self.assertEqual(rels_with_corpus.count(), 3)

        # Query without corpus filter: expect only structural relationships
        rels_no_corpus = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id, user=self.user1, corpus_id=None, use_cache=False
        )
        self.assertEqual(rels_no_corpus.count(), 1)

    def test_caching(self):
        """Test that caching works correctly with per-user keys."""
        # First call should hit the database
        with patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_document_permission",
            return_value=True,
        ), patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_corpus_permission",
            return_value=True,
        ):
            with self.assertNumQueries(1):
                rels1 = RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    use_cache=True,
                )
                list(rels1)  # Force evaluation

            # Second call should use cache
            with self.assertNumQueries(0):
                rels2 = RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    use_cache=True,
                )
                list(rels2)  # Force evaluation

            # Different user should have different cache
            with self.assertNumQueries(1):
                rels3 = RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user2,
                    corpus_id=self.corpus.id,
                    use_cache=True,
                )
                list(rels3)  # Force evaluation

    def test_cache_invalidation(self):
        """Test that cache is invalidated when relationships change."""
        # Cache the relationships
        rels1 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            use_cache=True,
        )
        count1 = rels1.count()

        # Invalidate cache for this document
        RelationshipQueryOptimizer.invalidate_cache(self.doc.id)

        # Create a new relationship
        new_rel = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=True,
        )
        new_rel.source_annotations.set([self.ann1])
        new_rel.target_annotations.set([self.ann2])

        # Next query should hit database and see new relationship
        with patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_document_permission",
            return_value=True,
        ), patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_corpus_permission",
            return_value=True,
        ):
            with self.assertNumQueries(1):
                rels2 = RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    use_cache=True,
                )
                count2 = rels2.count()

        self.assertEqual(count2, count1 + 1)

    @patch("opencontractserver.annotations.query_optimizer.connection")
    def test_materialized_view_fallback(self, mock_connection):
        """Test fallback when materialized view is unavailable."""
        # Mock the materialized view to be unavailable
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        # Should fall back to regular query
        summary = RelationshipQueryOptimizer.get_relationship_summary(
            document_id=self.doc.id, corpus_id=self.corpus.id, user=self.user1
        )

        # Verify summary contains expected data
        self.assertIn("relationship_count", summary)
        self.assertIn("label_types", summary)
        self.assertIn("pages_with_relationships", summary)

        # Check the counts match actual data (user1 perspective)
        self.assertEqual(
            summary["relationship_count"], 2
        )  # All relationships in corpus owned or public

    @patch("opencontractserver.annotations.query_optimizer.connection")
    def test_materialized_view_success_path(self, mock_connection):
        """When MV returns a row, ensure summary is sourced from MV and values are mapped correctly."""
        # Mock a MV row
        mock_cursor = MagicMock()
        # document_id, corpus_id, relationship_count, label_types, pages_with_relationships, last_refreshed
        mv_row = (self.doc.id, self.corpus.id, 5, 3, [1, 2], "2025-01-01T00:00:00Z")
        mock_cursor.fetchone.return_value = mv_row
        mock_connection.cursor.return_value.__enter__.return_value = mock_cursor

        # Call summary
        summary = RelationshipQueryOptimizer.get_relationship_summary(
            document_id=self.doc.id, corpus_id=self.corpus.id, user=self.user1
        )

        # Validate fields
        self.assertEqual(summary["document_id"], self.doc.id)
        self.assertEqual(summary["corpus_id"], self.corpus.id)
        self.assertEqual(summary["relationship_count"], 5)
        self.assertEqual(summary["label_types"], 3)
        self.assertEqual(summary["pages_with_relationships"], [1, 2])
        self.assertEqual(summary["source"], "materialized_view")

    def test_structural_filtering(self):
        """Test filtering structural vs non-structural relationships."""
        # Create a structural relationship
        structural_rel = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user1,
            is_public=True,
            structural=True,
        )
        structural_rel.source_annotations.set([self.ann1])
        structural_rel.target_annotations.set([self.ann2])

        # Get only structural relationships
        structural_rels = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            structural=True,
            use_cache=False,
        )
        self.assertEqual(structural_rels.count(), 1)

        # Get only non-structural relationships
        non_structural_rels = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            structural=False,
            use_cache=False,
        )
        self.assertEqual(non_structural_rels.count(), 2)  # rel_public and rel_private

    def test_prefetch_related_optimization(self):
        """Test that relationships are properly prefetched."""
        rels = list(
            RelationshipQueryOptimizer.get_document_relationships(
                document_id=self.doc.id,
                user=self.user1,
                corpus_id=self.corpus.id,
                use_cache=False,
            )
        )

        # Access prefetched data without additional queries
        with self.assertNumQueries(0):
            for rel in rels:
                # These should be prefetched
                _ = rel.relationship_label
                _ = rel.creator
                _ = list(rel.source_annotations.all())
                _ = list(rel.target_annotations.all())

    def test_analysis_filtering(self):
        """Test filtering by analysis: None => user+structural;
        0 => user+structural; specific => that analysis+structural."""
        # Simulate analysis_id mapping used by GraphQL layer: __none__ => None,
        # 0 => user relationships

        # analysis_id None: expect only user-created (analysis is null) + structural
        # For user1 perspective with corpus filter -> rel_public (is_public True)
        # and rel_private (creator user1, analysis null)
        # analysis relationships are excluded here
        rels_none = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            analysis_id=None,
            use_cache=False,
        )
        # rel_public + rel_private => 2
        self.assertEqual(rels_none.count(), 2)

        # analysis_id 0 => user relationships (analysis null) + structural
        rels_user = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            analysis_id=0,
            use_cache=False,
        )
        self.assertEqual(rels_user.count(), 2)

        # analysis_id specific => that analysis + structural
        rels_a1 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            analysis_id=self.analysis1.id,
            use_cache=False,
        )
        self.assertEqual(rels_a1.count(), 1)
        self.assertIn(self.rel_analysis1.id, list(rels_a1.values_list("id", flat=True)))

        rels_a2 = RelationshipQueryOptimizer.get_document_relationships(
            document_id=self.doc.id,
            user=self.user1,
            corpus_id=self.corpus.id,
            analysis_id=self.analysis2.id,
            use_cache=False,
        )
        self.assertEqual(rels_a2.count(), 1)
        self.assertIn(self.rel_analysis2.id, list(rels_a2.values_list("id", flat=True)))

    def test_cache_key_generation(self):
        """Test that cache keys are unique for different query parameters."""
        # Different keys for different users
        key1 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=None,
            structural=None,
            analysis_id=None,
        )
        key2 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=2,
            corpus_id=1,
            pages=None,
            structural=None,
            analysis_id=None,
        )
        self.assertNotEqual(key1, key2)

        # Different keys for different pages
        key3 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=[1, 2],
            structural=None,
            analysis_id=None,
        )
        key4 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=[3, 4],
            structural=None,
            analysis_id=None,
        )
        self.assertNotEqual(key3, key4)

        # Different keys for structural flag
        key5 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=None,
            structural=True,
            analysis_id=None,
        )
        key6 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=None,
            structural=False,
            analysis_id=None,
        )
        self.assertNotEqual(key5, key6)

        # Order-insensitivity and duplicate tolerance for pages
        key7 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=[2, 1, 2],
            structural=None,
            analysis_id=None,
        )
        key8 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=[1, 2],
            structural=None,
            analysis_id=None,
        )
        self.assertEqual(key7, key8)

        # Differentiate None vs 0 analysis_id
        key9 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=None,
            structural=None,
            analysis_id=None,
        )
        key10 = RelationshipQueryOptimizer._get_cache_key(
            document_id=1,
            user_id=1,
            corpus_id=1,
            pages=None,
            structural=None,
            analysis_id=0,
        )
        self.assertNotEqual(key9, key10)

    def test_invalidate_cache_doc_corpus_deletes_keys(self):
        """Invalidating (doc, corpus) removes cached keys for that pair, forcing a DB hit next call."""
        # Warm cache
        with patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_document_permission",
            return_value=True,
        ), patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_corpus_permission",
            return_value=True,
        ):
            rels_cached = RelationshipQueryOptimizer.get_document_relationships(
                document_id=self.doc.id,
                user=self.user1,
                corpus_id=self.corpus.id,
                use_cache=True,
            )
            list(rels_cached)

            # Invalidate for (doc, corpus)
            RelationshipQueryOptimizer.invalidate_cache(self.doc.id, self.corpus.id)

            # Next call should miss cache -> 1 query
            with self.assertNumQueries(1):
                rels_after = RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    use_cache=True,
                )
                list(rels_after)

    def test_invalidate_cache_doc_only_removes_all_keys(self):
        """Invalidating by document removes all cached keys for that document (any corpus/pages)."""
        with patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_document_permission",
            return_value=True,
        ), patch(
            "opencontractserver.annotations.query_optimizer.RelationshipQueryOptimizer._check_corpus_permission",
            return_value=True,
        ):
            # Warm two different cache entries for same doc/corpus but different pages
            list(
                RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    pages=[1],
                    use_cache=True,
                )
            )
            list(
                RelationshipQueryOptimizer.get_document_relationships(
                    document_id=self.doc.id,
                    user=self.user1,
                    corpus_id=self.corpus.id,
                    pages=[2],
                    use_cache=True,
                )
            )

            # Invalidate by document
            RelationshipQueryOptimizer.invalidate_cache(self.doc.id)

            # Both variants should now cause a DB query on first access
            with self.assertNumQueries(1):
                list(
                    RelationshipQueryOptimizer.get_document_relationships(
                        document_id=self.doc.id,
                        user=self.user1,
                        corpus_id=self.corpus.id,
                        pages=[1],
                        use_cache=True,
                    )
                )
            with self.assertNumQueries(1):
                list(
                    RelationshipQueryOptimizer.get_document_relationships(
                        document_id=self.doc.id,
                        user=self.user1,
                        corpus_id=self.corpus.id,
                        pages=[2],
                        use_cache=True,
                    )
                )
