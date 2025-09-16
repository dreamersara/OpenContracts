"""
GraphQL authorization tests for navigation, page annotations, and summary.
"""

from __future__ import annotations

from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class GraphQLAuthzTest(BaseFixtureTestCase):
    """
    Ensures anonymous vs authenticated access returns expected visibility.
    For simplicity, mark annotations as non-public and assert anonymous sees none.
    """

    def setUp(self):
        super().setUp()
        self.client = Client(schema)
        self.corpus = Corpus.objects.create(title="AuthZ Corpus", creator=self.user)
        self.label = AnnotationLabel.objects.create(
            text="AuthZ Label", creator=self.user
        )

        anns: list[Annotation] = []
        for page in [1, 2]:
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"NS p{page}",
                    creator=self.user,
                    structural=False,
                    is_public=False,  # ensure not public
                )
            )
        Annotation.objects.bulk_create(anns)

        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_anonymous_cannot_access_private_document(self):
        nav_q = """
        query GetNav($docId: String!, $corpusId: ID!) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId) { id page }
          }
        }
        """
        res = self.client.execute(
            nav_q,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
            context_value=type(
                "obj",
                (object,),
                {
                    "user": type(
                        "anon", (), {"is_anonymous": True, "is_superuser": False}
                    )()
                },
            )(),
        )
        # Private document should not be accessible; expect explicit permission error
        assert "errors" in res and any(
            "Permission denied" in e.get("message", "") for e in res["errors"]
        )

        page_q = """
        query PageAnn($docId: String!, $corpusId: ID!, $page: Int!) {
          document(id: $docId) {
            id
            pageAnnotations(corpusId: $corpusId, page: $page) { id page }
          }
        }
        """
        res2 = self.client.execute(
            page_q,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid, "page": 1},
            context_value=type(
                "obj",
                (object,),
                {
                    "user": type(
                        "anon", (), {"is_anonymous": True, "is_superuser": False}
                    )()
                },
            )(),
        )
        assert "errors" in res2 and any(
            "Permission denied" in e.get("message", "") for e in res2["errors"]
        )

    def test_authenticated_sees_creator_data(self):
        nav_q = """
        query GetNav($docId: String!, $corpusId: ID!) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId) { id page }
          }
        }
        """
        res = self.client.execute(
            nav_q,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res, res.get("errors")
        assert len(res["data"]["document"]["annotationNavigation"]) == 2

