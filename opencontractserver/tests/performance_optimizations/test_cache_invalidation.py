"""
Tests targeted cache invalidation on refresh_annotation_summary_mv(document_id, corpus_id).
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tasks.materialized_view_tasks import (
    refresh_annotation_summary_mv,
)
from opencontractserver.tests.base import BaseFixtureTestCase


class CacheInvalidationTest(BaseFixtureTestCase):
    """
    Ensures that summary cache for a specific (doc, corpus) is invalidated by targeted refresh.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(title="Cache Corpus", creator=self.user)
        self.label = AnnotationLabel.objects.create(
            text="Cache Label", creator=self.user
        )

        # Start with 1 non-structural annotation on page 1
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.label,
            raw_text="A1",
            creator=self.user,
            structural=False,
        )

        # Populate MV and cache the summary
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

        first = AnnotationQueryOptimizer.get_annotation_summary(
            self.doc.id, self.corpus.id, user=self.user, use_mv=True
        )
        assert first["annotation_count"] == 1

    def test_targeted_refresh_invalidates_cache_key(self):
        # Add another non-structural annotation (not yet reflected in MV or cache)
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=2,
            annotation_label=self.label,
            raw_text="A2",
            creator=self.user,
            structural=False,
        )

        # Ensure MV includes new row by refreshing (targeted call)
        refresh_annotation_summary_mv(document_id=self.doc.id, corpus_id=self.corpus.id)

        # Next call should read updated MV and not serve stale cached value
        after = AnnotationQueryOptimizer.get_annotation_summary(
            self.doc.id, self.corpus.id, user=self.user, use_mv=True
        )
        assert after["annotation_count"] == 2
