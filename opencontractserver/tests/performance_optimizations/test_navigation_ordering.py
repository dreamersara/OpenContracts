"""
Tests for navigation ordering (page then id) and structural exclusion.
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class NavigationOrderingTest(BaseFixtureTestCase):
    """
    Ensures navigation data is ordered by page then id and excludes structural rows.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(title="Nav Order Corpus", creator=self.user)
        self.label = AnnotationLabel.objects.create(text="Nav Label", creator=self.user)

        # Create structural and non-structural annotations with mixed pages and ids
        anns: list[Annotation] = []
        # Structural that should be excluded
        anns.append(
            Annotation(
                document=self.doc,
                corpus=self.corpus,
                page=2,
                annotation_label=self.label,
                raw_text="S p2",
                creator=self.user,
                structural=True,
            )
        )
        # Non-structural
        for page in [1, 1, 2, 3, 3, 3]:
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"NS p{page}",
                    creator=self.user,
                    structural=False,
                )
            )
        Annotation.objects.bulk_create(anns)

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )

    def test_navigation_is_ordered_and_excludes_structural(self):
        nav = AnnotationQueryOptimizer.get_navigation_annotations(
            user=self.user,
            document_id=self.doc.id,
            corpus_id=self.corpus.id,
            use_mv=True,
        )

        # Normalize to list of dicts regardless of MV vs queryset path
        if (
            hasattr(nav, "values")
            or hasattr(nav, "__iter__")
            and not isinstance(nav, list)
        ):
            nav_list = [
                {
                    "id": a.id,
                    "page": a.page,
                    "bounding_box": getattr(a, "bounding_box", None),
                }
                for a in nav
            ]
        else:
            nav_list = nav

        assert len(nav_list) == 6  # excludes the single structural

        # Check ordering by page then id
        pages = [n["page"] for n in nav_list]
        assert pages == sorted(pages)  # pages non-decreasing

        # Within equal pages, ids should be non-decreasing
        for page in sorted(set(pages)):
            ids = [n["id"] for n in nav_list if n["page"] == page]
            assert ids == sorted(ids)
