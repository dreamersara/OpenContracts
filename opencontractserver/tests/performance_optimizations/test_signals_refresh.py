"""
Side-effect tests for signals using Celery eager mode: verify materialized views update.
"""

from __future__ import annotations

from django.db import connection
from django.db.models.signals import post_save

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.signals import (
    ANNOT_CREATE_UID,
    process_annot_on_create_atomic,
)
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class SignalsRefreshSchedulingTest(BaseFixtureTestCase):
    """
    Creates annotations and asserts MV contents change accordingly (Celery eager).
    """

    def setUp(self):
        super().setUp()
        # Reconnect the annotation post_save signal just for this test
        post_save.connect(
            process_annot_on_create_atomic,
            sender=Annotation,
            dispatch_uid=ANNOT_CREATE_UID,
        )
        self.label = AnnotationLabel.objects.create(text="Sig Label", creator=self.user)

    def tearDown(self):
        # Disconnect after test to keep global state stable
        post_save.disconnect(
            process_annot_on_create_atomic,
            sender=Annotation,
            dispatch_uid=ANNOT_CREATE_UID,
        )
        super().tearDown()

    def _nav_count(self, document_id: int, corpus_id: int) -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM annotation_navigation_mv
                WHERE document_id = %s AND corpus_id = %s
                """,
                [document_id, corpus_id],
            )
            return int(cursor.fetchone()[0])

    def _summary_counts(self, document_id: int, corpus_id: int):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT annotation_count, structural_count, page_count
                FROM annotation_summary_mv
                WHERE document_id = %s AND corpus_id = %s
                """,
                [document_id, corpus_id],
            )
            row = cursor.fetchone()
            return row if row else (None, None, None)

    def test_non_structural_side_effects(self):
        """
        Creating a non-structural annotation should refresh both MVs.
        """
        corpus = Corpus.objects.create(title="Signals A", creator=self.user)

        # Baseline: no rows for this doc/corpus in MVs
        assert self._nav_count(self.doc.id, corpus.id) == 0
        a_count, s_count, p_count = self._summary_counts(self.doc.id, corpus.id)
        assert a_count is None and s_count is None and p_count is None

        # Create non-structural annotation (triggers both refresh tasks)
        Annotation.objects.create(
            document=self.doc,
            corpus=corpus,
            page=1,
            annotation_label=self.label,
            raw_text="NS",
            creator=self.user,
            structural=False,
        )

        # After eager tasks, navigation MV should have 1 row; summary should reflect 1 non-structural
        assert self._nav_count(self.doc.id, corpus.id) == 1
        a_count, s_count, p_count = self._summary_counts(self.doc.id, corpus.id)
        assert (a_count, s_count, p_count) == (1, 0, 1)

    def test_structural_side_effects(self):
        """
        Creating a structural annotation should refresh summary only.
        """
        corpus = Corpus.objects.create(title="Signals B", creator=self.user)

        assert self._nav_count(self.doc.id, corpus.id) == 0
        a_count, s_count, p_count = self._summary_counts(self.doc.id, corpus.id)
        assert a_count is None and s_count is None and p_count is None

        # Create structural annotation (triggers summary refresh only)
        Annotation.objects.create(
            document=self.doc,
            corpus=corpus,
            page=2,
            annotation_label=self.label,
            raw_text="S",
            creator=self.user,
            structural=True,
        )

        # Navigation MV should still be empty; summary should reflect 1 structural
        assert self._nav_count(self.doc.id, corpus.id) == 0
        a_count, s_count, p_count = self._summary_counts(self.doc.id, corpus.id)
        assert (a_count, s_count, p_count) == (0, 1, 1)

