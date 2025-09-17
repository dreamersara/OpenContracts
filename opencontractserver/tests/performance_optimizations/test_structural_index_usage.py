"""
EXPLAIN test to confirm structural-path index usage (idx_ann_doc_page_struct).
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class StructuralIndexUsageTest(BaseFixtureTestCase):
    """
    Confirms that structural=true with page IN uses an index scan.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(title="StructIdx Corpus", creator=self.user)
        self.label = AnnotationLabel.objects.create(
            text="StructIdx Label", creator=self.user
        )

        # Insert many structural annotations across pages to make index usage more likely
        anns = []
        for page in range(1, 51):
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"S p{page}",
                    creator=self.user,
                    structural=True,
                )
            )
        Annotation.objects.bulk_create(anns)

    def _uses_index(self, sql: str, params: list[int]) -> bool:
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN (FORMAT JSON) " + sql, params)
            plan = cursor.fetchone()[0][0]
            plan_str = str(plan)
            return ("Index Scan" in plan_str) or ("Bitmap Index Scan" in plan_str)

    def test_structural_index_is_used(self):
        sql = """
            SELECT *
            FROM annotations_annotation
            WHERE document_id = %s
              AND page IN (5,10,15)
              AND structural = true
        """
        assert self._uses_index(sql, [self.doc.id])
