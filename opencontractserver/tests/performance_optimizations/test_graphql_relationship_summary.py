from django.test import TestCase
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import (
    Annotation,
    AnnotationLabel,
    Relationship,
)
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.types.enums import LabelType
from opencontractserver.users.models import User


class RelationshipSummaryFieldTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner", email="owner@example.com", password="pass"
        )
        self.doc = Document.objects.create(
            title="D",
            creator=self.user,
            file_type="application/pdf",
            pdf_file="test.pdf",
            is_public=True,
        )
        self.corpus = Corpus.objects.create(title="C", creator=self.user)
        label = AnnotationLabel.objects.create(
            text="Span", creator=self.user, label_type=LabelType.SPAN_LABEL
        )
        a1 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=label,
            raw_text="A1",
            creator=self.user,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )
        a2 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=2,
            annotation_label=label,
            raw_text="A2",
            creator=self.user,
            structural=False,
            bounding_box={"x": 1, "y": 1, "width": 10, "height": 10},
        )
        rel = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            creator=self.user,
            is_public=True,
        )
        rel.source_annotations.set([a1])
        rel.target_annotations.set([a2])

        self.client = Client(schema)
        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_relationship_summary_field(self):
        q = """
        query($docId: String!, $corpusId: ID!) {
          document(id: $docId) {
            relationshipSummary(corpusId: $corpusId)
          }
        }
        """
        res = self.client.execute(
            q,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res
        summary = res["data"]["document"]["relationshipSummary"]
        assert "relationship_count" in summary
        assert summary["relationship_count"] >= 1
        assert "pages_with_relationships" in summary
