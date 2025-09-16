"""
EXPLAIN-based tests to confirm index scans for analysis filter variants.
"""

from __future__ import annotations

from typing import Any

from django.db import connection

from opencontractserver.analyzer.models import Analysis, Analyzer
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class AnalysisFilterIndexUsageTest(BaseFixtureTestCase):
    """
    Confirms planner uses index scans for analysis-related filters.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(
            title="Index Analysis Corpus", creator=self.user
        )
        self.label = AnnotationLabel.objects.create(text="Idx Label", creator=self.user)
        self.analyzer = Analyzer.objects.create(
            id="idx_analyzer",
            description="Analyzer for index tests",
            creator=self.user,
            manifest={},
            task_name="test_task",
        )
        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer, analyzed_corpus=self.corpus, creator=self.user
        )

        # 10 pages, 20 annotations/page: 2 structural + 18 non-structural.
        anns: list[Annotation] = []
        for page in range(1, 11):
            for i in range(20):
                anns.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"A{i} p{page}",
                        creator=self.user,
                        structural=(i < 2),
                        analysis=(
                            self.analysis if (not (i < 2) and i % 3 == 0) else None
                        ),
                    )
                )
        Annotation.objects.bulk_create(anns)

    def _plan_uses_index(self, sql: str, params: list[Any] | None = None) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (FORMAT JSON) " + sql, params or [])
            plan = cursor.fetchone()[0][0]
            plan_str = str(plan)
            return ("Index Scan" in plan_str) or ("Bitmap Index Scan" in plan_str)

    def test_index_used_for_user_annotations_isnull(self):
        """
        Expect index scan for structural=false AND analysis_id IS NULL with page IN.
        """
        sql = """
            SELECT *
            FROM annotations_annotation
            WHERE document_id = %s
              AND corpus_id = %s
              AND page IN (1,2,3)
              AND structural = false
              AND analysis_id IS NULL
        """
        assert self._plan_uses_index(sql, [self.doc.id, self.corpus.id])

    def test_index_used_for_specific_analysis_id(self):
        """
        Expect index scan for structural=false AND analysis_id=<id> with page IN.
        """
        sql = """
            SELECT *
            FROM annotations_annotation
            WHERE document_id = %s
              AND corpus_id = %s
              AND page IN (4,5,6)
              AND structural = false
              AND analysis_id = %s
        """
        assert self._plan_uses_index(
            sql, [self.doc.id, self.corpus.id, self.analysis.id]
        )

