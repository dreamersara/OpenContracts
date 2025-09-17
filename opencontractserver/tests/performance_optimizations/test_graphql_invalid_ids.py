"""
GraphQL: invalid global IDs should not error and should return empty results.
"""

from __future__ import annotations

from django.db import connection
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class GraphQLInvalidIDsTest(BaseFixtureTestCase):
    """
    Use valid document ID but non-existent corpus/analysis IDs to ensure
    resolvers return empty results without GraphQL errors.
    """

    def setUp(self):
        super().setUp()
        self.client = Client(schema)

        # Create a corpus and some annotations for the valid path
        self.corpus = Corpus.objects.create(
            title="InvalidIDs Corpus", creator=self.user
        )
        self.label = AnnotationLabel.objects.create(text="Inv Label", creator=self.user)

        anns: list[Annotation] = []
        for page in [1, 2, 3]:
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"NS p{page}",
                    creator=self.user,
                    structural=False,
                )
            )
        Annotation.objects.bulk_create(anns)

        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

        # Clearly non-existent ids
        self.bad_corpus_gid = to_global_id("CorpusType", 99999999)
        self.bad_analysis_gid = to_global_id("AnalysisType", 99999999)

    def test_navigation_with_nonexistent_corpus(self):
        query = """
        query GetNav($docId: String!, $corpusId: ID!) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId) { id page }
          }
        }
        """
        res = self.client.execute(
            query,
            variables={"docId": self.doc_gid, "corpusId": self.bad_corpus_gid},
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res, res.get("errors")
        assert res["data"]["document"]["annotationNavigation"] == []

    def test_page_annotations_with_nonexistent_corpus(self):
        query = """
        query PageAnn($docId: String!, $corpusId: ID!, $page: Int!) {
          document(id: $docId) {
            id
            pageAnnotations(corpusId: $corpusId, page: $page) { id page structural }
          }
        }
        """
        res = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.bad_corpus_gid,
                "page": 1,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res, res.get("errors")
        assert res["data"]["document"]["pageAnnotations"] == []

    def test_navigation_with_nonexistent_analysis(self):
        query = """
        query GetNavWithAnalysis($docId: String!, $corpusId: ID!, $analysisId: ID) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId, analysisId: $analysisId) { id page }
          }
        }
        """
        res = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "analysisId": self.bad_analysis_gid,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res, res.get("errors")
        assert res["data"]["document"]["annotationNavigation"] == []
