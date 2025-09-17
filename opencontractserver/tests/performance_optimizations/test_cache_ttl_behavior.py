"""
Cache TTL behavior: override CACHE_TTL small; assert expired entry forces re-read.
"""

from __future__ import annotations

import time

from django.db import connection
from django.test import override_settings

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class CacheTTLBehaviorTest(BaseFixtureTestCase):
    """
    Verifies summary cache expires and subsequent call re-reads MV.
    """

    @override_settings()
    def test_cache_expiry_forces_requery(self):
        # Create doc/corpus data
        corpus = Corpus.objects.create(title="TTL Corpus", creator=self.user)
        label = AnnotationLabel.objects.create(text="TTL Label", creator=self.user)
        Annotation.objects.create(
            document=self.doc,
            corpus=corpus,
            page=1,
            annotation_label=label,
            raw_text="A1",
            creator=self.user,
            structural=False,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

        # Force very small TTL
        original_ttl = AnnotationQueryOptimizer.CACHE_TTL
        AnnotationQueryOptimizer.CACHE_TTL = 1
        try:
            first = AnnotationQueryOptimizer.get_annotation_summary(
                self.doc.id, corpus.id, user=self.user, use_mv=True
            )
            assert first["annotation_count"] == 1

            # Add another annotation, refresh MV
            Annotation.objects.create(
                document=self.doc,
                corpus=corpus,
                page=2,
                annotation_label=label,
                raw_text="A2",
                creator=self.user,
                structural=False,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )

            # While cache is still alive, count should remain 1
            still_cached = AnnotationQueryOptimizer.get_annotation_summary(
                self.doc.id, corpus.id, user=self.user, use_mv=True
            )
            assert still_cached["annotation_count"] == 1

            # Wait for TTL to expire
            time.sleep(1.2)
            refreshed = AnnotationQueryOptimizer.get_annotation_summary(
                self.doc.id, corpus.id, user=self.user, use_mv=True
            )
            assert refreshed["annotation_count"] == 2
        finally:
            AnnotationQueryOptimizer.CACHE_TTL = original_ttl
