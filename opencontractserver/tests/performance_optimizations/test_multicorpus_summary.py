"""
Tests that materialized view summary is correct across multiple corpora for the same document.
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class MultiCorpusSummaryTest(BaseFixtureTestCase):
    """
    Validates MV produces distinct rows and correct aggregates for the same document in different corpora.
    """

    def setUp(self):
        super().setUp()
        self.label = AnnotationLabel.objects.create(text="MC Label", creator=self.user)

        # Create two corpora for the same document
        self.corpus_a = Corpus.objects.create(title="Corpus A", creator=self.user)
        self.corpus_b = Corpus.objects.create(title="Corpus B", creator=self.user)

        # Corpus A: 1 page -> 1 structural + 2 non-structural
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus_a,
            page=1,
            annotation_label=self.label,
            raw_text="S A",
            creator=self.user,
            structural=True,
        )
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus_a,
            page=1,
            annotation_label=self.label,
            raw_text="NS1 A",
            creator=self.user,
            structural=False,
        )
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus_a,
            page=1,
            annotation_label=self.label,
            raw_text="NS2 A",
            creator=self.user,
            structural=False,
        )

        # Corpus B: 2 pages -> 2 structural + 2 non-structural (one per page)
        for page in [1, 2]:
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus_b,
                page=page,
                annotation_label=self.label,
                raw_text=f"S B{page}",
                creator=self.user,
                structural=True,
            )
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus_b,
                page=page,
                annotation_label=self.label,
                raw_text=f"NS B{page}",
                creator=self.user,
                structural=False,
            )

        # Refresh materialized view
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

    def test_multicorpus_summary_counts(self):
        """
        Verify summary rows and counts are independent per corpus for the same document.
        """
        sum_a = AnnotationQueryOptimizer.get_annotation_summary(
            self.doc.id, self.corpus_a.id, user=self.user, use_mv=True
        )
        assert sum_a["annotation_count"] == 2
        assert sum_a["structural_count"] == 1
        assert sum_a["page_count"] == 1
        assert sum_a["first_page"] == 1
        assert sum_a["last_page"] == 1

        sum_b = AnnotationQueryOptimizer.get_annotation_summary(
            self.doc.id, self.corpus_b.id, user=self.user, use_mv=True
        )
        assert sum_b["annotation_count"] == 2
        assert sum_b["structural_count"] == 2
        assert sum_b["page_count"] == 2
        assert sum_b["first_page"] == 1
        assert sum_b["last_page"] == 2

