from __future__ import annotations

from django.db import connection
from django.test import TestCase

from opencontractserver.annotations.models import (
    Annotation,
    AnnotationLabel,
    Relationship,
)
from opencontractserver.annotations.query_optimizer import RelationshipQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.tasks.materialized_view_tasks import (
    refresh_relationship_summary_mv,
)
from opencontractserver.types.enums import LabelType
from opencontractserver.users.models import User


class RelationshipMaterializedViewRefreshTest(TestCase):
    """
    Validate that relationship_summary_mv is refreshed and per-user caches are updated.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="mvuser", email="mv@example.com", password="testpass123"
        )
        self.doc = Document.objects.create(
            title="MV Doc",
            creator=self.user,
            file_type="application/pdf",
            pdf_file="test.pdf",
        )
        self.corpus = Corpus.objects.create(title="MV Corpus", creator=self.user)

        self.ann_label = AnnotationLabel.objects.create(
            text="Span", creator=self.user, label_type=LabelType.SPAN_LABEL
        )

        # Annotations on two pages
        self.a1 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.ann_label,
            raw_text="A1",
            creator=self.user,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )
        self.a2 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=2,
            annotation_label=self.ann_label,
            raw_text="A2",
            creator=self.user,
            structural=False,
            bounding_box={"x": 5, "y": 5, "width": 10, "height": 10},
        )

        # Initial relationship (page 1 -> page 2)
        self.rel1 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=None,
            creator=self.user,
            is_public=True,
        )
        self.rel1.source_annotations.set([self.a1])
        self.rel1.target_annotations.set([self.a2])

        # Ensure MV has data
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY relationship_summary_mv"
            )

    def test_refresh_updates_summary_and_cache(self):
        # Warm cache by fetching summary (registers user in registry)
        s1 = RelationshipQueryOptimizer.get_relationship_summary(
            document_id=self.doc.id, corpus_id=self.corpus.id, user=self.user
        )
        assert s1["relationship_count"] == 1
        assert s1["pages_with_relationships"] == [1, 2]

        # Add another relationship
        rel2 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=None,
            creator=self.user,
            is_public=True,
        )
        rel2.source_annotations.set([self.a2])
        rel2.target_annotations.set([self.a1])

        # Targeted refresh (full MV refresh under the hood, then per-user cache overwrite)
        refresh_relationship_summary_mv(
            document_id=self.doc.id, corpus_id=self.corpus.id
        )

        # After refresh, summary and cached value should reflect 2 relationships
        s2 = RelationshipQueryOptimizer.get_relationship_summary(
            document_id=self.doc.id, corpus_id=self.corpus.id, user=self.user
        )
        assert s2["relationship_count"] == 2
        # Pages should remain [1, 2]
        assert s2["pages_with_relationships"] == [1, 2]
        assert s2["source"] in ("materialized_view", "direct_query")
