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


class PageRelationshipsPermissionsAndStructuralTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password="pass"
        )
        self.other = User.objects.create_user(
            username="other", email="other@example.com", password="pass"
        )

        self.doc = Document.objects.create(
            title="Doc",
            creator=self.owner,
            file_type="application/pdf",
            pdf_file="test.pdf",
            is_public=False,
        )
        self.corpus = Corpus.objects.create(title="C", creator=self.owner)

        label = AnnotationLabel.objects.create(
            text="Span", creator=self.owner, label_type=LabelType.SPAN_LABEL
        )

        a1 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=label,
            raw_text="A1",
            creator=self.owner,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )
        a2 = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=label,
            raw_text="A2",
            creator=self.owner,
            structural=False,
            bounding_box={"x": 1, "y": 1, "width": 10, "height": 10},
        )

        # Non-structural relationship
        rel = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            creator=self.owner,
            is_public=True,
            structural=False,
        )
        rel.source_annotations.set([a1])
        rel.target_annotations.set([a2])

        # Structural relationship
        rels = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            creator=self.owner,
            is_public=True,
            structural=True,
        )
        rels.source_annotations.set([a1])
        rels.target_annotations.set([a2])

        self.client = Client(schema)
        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_permission_denied_for_private_doc(self):
        query = """
        query($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) { id }
          }
        }
        """
        res = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1],
            },
            context_value=type("obj", (object,), {"user": self.other})(),
        )
        assert "errors" in res
        assert "Permission denied" in res["errors"][0]["message"]

    def test_structural_filter(self):
        query = """
        query($docId: String!, $corpusId: ID!, $pages: [Int!]!, $structural: Boolean) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages, structural: $structural) { id structural }
          }
        }
        """

        # Owner context, structural=true
        res_true = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1],
                "structural": True,
            },
            context_value=type("obj", (object,), {"user": self.owner})(),
        )
        assert "errors" not in res_true
        assert all(
            r["structural"] is True
            for r in res_true["data"]["document"]["pageRelationships"]
        )  # noqa: E501

        # Owner context, structural=false
        res_false = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1],
                "structural": False,
            },
            context_value=type("obj", (object,), {"user": self.owner})(),
        )
        assert "errors" not in res_false
        assert all(
            r["structural"] is False
            for r in res_false["data"]["document"]["pageRelationships"]
        )  # noqa: E501
