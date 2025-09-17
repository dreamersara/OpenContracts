"""
Tests that annotation_summary_mv pages_with_annotations is sorted, unique, and matches first/last/page_count.
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class SummaryPagesIntegrityTest(BaseFixtureTestCase):
    """
    Validates pages_with_annotations array integrity in the summary MV.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(
            title="Pages Integrity Corpus", creator=self.user
        )
        self.label = AnnotationLabel.objects.create(
            text="Pages Label", creator=self.user
        )

        # Create non-structural annotations on scattered pages with duplicates
        for page in [5, 1, 3, 3, 7, 1, 9]:
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label,
                raw_text=f"NS p{page}",
                creator=self.user,
                structural=False,
            )

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

    def test_pages_array_integrity(self):
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            self.doc.id, self.corpus.id, user=self.user, use_mv=True
        )

        pages = summary["pages_with_annotations"]
        assert pages == sorted(set(pages))  # sorted, unique

        assert summary["first_page"] == min(pages)
        assert summary["last_page"] == max(pages)
        assert summary["page_count"] == len(pages)
