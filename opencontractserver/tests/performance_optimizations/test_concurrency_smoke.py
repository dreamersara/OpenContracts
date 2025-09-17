"""
Concurrency smoke: burst-create annotations inside transactions and verify MVs reflect totals.
"""

from __future__ import annotations

import time

from django.db import connection, transaction
from django.db.models.signals import post_save

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.signals import (
    ANNOT_CREATE_UID,
    process_annot_on_create_atomic,
)
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class ConcurrencySmokeTest(BaseFixtureTestCase):
    """
    Creates annotations in two separate transactions; verifies both MVs reflect totals after eager tasks.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(
            title="Concurrent Corpus", creator=self.user
        )
        self.label = AnnotationLabel.objects.create(
            text="Conc Label", creator=self.user
        )
        # Reconnect annotation post_save so MV refresh tasks run in eager mode
        post_save.connect(
            process_annot_on_create_atomic,
            sender=Annotation,
            dispatch_uid=ANNOT_CREATE_UID,
        )

    def tearDown(self):
        # Disconnect to restore base class behavior
        post_save.disconnect(
            process_annot_on_create_atomic,
            sender=Annotation,
            dispatch_uid=ANNOT_CREATE_UID,
        )
        super().tearDown()

    def _summary_counts(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(SUM(annotation_count),0), COALESCE(SUM(structural_count),0)
                FROM annotation_summary_mv
                WHERE document_id = %s AND corpus_id = %s
                """,
                [self.doc.id, self.corpus.id],
            )
            row = cursor.fetchone()
            return int(row[0]), int(row[1])

    def _nav_count(self):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM annotation_navigation_mv
                WHERE document_id = %s AND corpus_id = %s
                """,
                [self.doc.id, self.corpus.id],
            )
            return int(cursor.fetchone()[0])

    def test_burst_insertions(self):
        # First transaction burst
        with transaction.atomic():
            for i in range(10):
                Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=1,
                    annotation_label=self.label,
                    raw_text=f"NS1-{i}",
                    creator=self.user,
                    structural=False,
                )

        # Second transaction burst
        with transaction.atomic():
            for i in range(5):
                Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=2,
                    annotation_label=self.label,
                    raw_text=f"S-{i}",
                    creator=self.user,
                    structural=True,
                )

        # After eager tasks triggered by signals, verify MVs
        # Give a tiny window for on_commit + eager tasks
        for _ in range(20):
            ann_count, struct_count = self._summary_counts()
            nav_count = self._nav_count()
            if ann_count == 10 and struct_count == 5 and nav_count == 10:
                break
            time.sleep(0.05)

        ann_count, struct_count = self._summary_counts()
        nav_count = self._nav_count()
        assert ann_count == 10
        assert struct_count == 5
        assert nav_count == 10
