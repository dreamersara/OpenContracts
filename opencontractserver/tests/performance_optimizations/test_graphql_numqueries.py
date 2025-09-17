"""
GraphQL query-count tests to prevent N+1 regressions for navigation and page annotations.
"""

from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class GraphQLNumQueriesTest(BaseFixtureTestCase):
    """
    Asserts that navigation and page annotations queries remain bounded (no N+1).
    """

    def setUp(self):
        super().setUp()
        self.client = Client(schema)
        self.corpus = Corpus.objects.create(title="NumQ Corpus", creator=self.user)
        self.label = AnnotationLabel.objects.create(
            text="NumQ Label", creator=self.user
        )

        # Create dataset: 3 pages, 10 non-structural per page + 1 structural per page
        anns: list[Annotation] = []
        for page in [1, 2, 3]:
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
            for i in range(10):
                anns.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"NS {i} p{page}",
                        creator=self.user,
                        structural=False,
                    )
                )
        Annotation.objects.bulk_create(anns)

        # Populate MVs for navigation to use MV path
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )

        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_navigation_query_numqueries(self):
        """
        Navigation query count should remain stable as data volume grows (no N+1).
        We compare query counts before and after adding many annotations.
        """
        query = """
        query GetNav($docId: String!, $corpusId: ID!) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId) {
              id
              page
              boundingBox
            }
          }
        }
        """

        with CaptureQueriesContext(connection) as ctx:
            result = self.client.execute(
                query,
                variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
                context_value=type("obj", (object,), {"user": self.user})(),
            )
        assert "errors" not in result, result.get("errors")

        baseline_count = len(ctx.captured_queries)

        # Inflate data volume significantly
        extra: list[Annotation] = []
        for page in range(1, 6):
            for i in range(50):  # add 250 more non-structural
                extra.append(
                    Annotation(
                        document=self.doc,
                        corpus=self.corpus,
                        page=page,
                        annotation_label=self.label,
                        raw_text=f"extra {i} p{page}",
                        creator=self.user,
                        structural=False,
                    )
                )
        Annotation.objects.bulk_create(extra)

        # Refresh MV so navigation uses the updated set
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )

        with CaptureQueriesContext(connection) as ctx2:
            result2 = self.client.execute(
                query,
                variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
                context_value=type("obj", (object,), {"user": self.user})(),
            )
        assert "errors" not in result2, result2.get("errors")

        # The query count should not grow with data volume (allow small variance)
        assert len(ctx2.captured_queries) <= baseline_count + 2

    def test_page_annotations_numqueries(self):
        """
        Page annotations query count should remain stable as data on that page grows.
        """
        query = """
        query PageAnn($docId: String!, $corpusId: ID!, $page: Int!) {
          document(id: $docId) {
            id
            pageAnnotations(corpusId: $corpusId, page: $page) {
              id
              page
              structural
              annotationLabel { id text }
              creator { id email }
            }
          }
        }
        """

        with CaptureQueriesContext(connection) as ctx:
            result = self.client.execute(
                query,
                variables={
                    "docId": self.doc_gid,
                    "corpusId": self.corpus_gid,
                    "page": 2,
                },
                context_value=type("obj", (object,), {"user": self.user})(),
            )
        assert "errors" not in result, result.get("errors")

        baseline = len(ctx.captured_queries)

        # Add many more annotations on page 2
        extra: list[Annotation] = []
        for i in range(200):
            extra.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=2,
                    annotation_label=self.label,
                    raw_text=f"extra-page2-{i}",
                    creator=self.user,
                    structural=False,
                )
            )
        Annotation.objects.bulk_create(extra)

        with CaptureQueriesContext(connection) as ctx2:
            result2 = self.client.execute(
                query,
                variables={
                    "docId": self.doc_gid,
                    "corpusId": self.corpus_gid,
                    "page": 2,
                },
                context_value=type("obj", (object,), {"user": self.user})(),
            )
        assert "errors" not in result2, result2.get("errors")

        # Query count should stay the same or increase by at most a couple due to caching/planning variance
        assert len(ctx2.captured_queries) <= baseline + 2
