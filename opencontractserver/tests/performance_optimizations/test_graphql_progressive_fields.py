"""
GraphQL tests for progressive fields on DocumentType: annotationNavigation and pageAnnotations.
"""

from __future__ import annotations

from django.db import connection
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.analyzer.models import Analysis, Analyzer
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase


class GraphQLProgressiveFieldsTest(BaseFixtureTestCase):
    """
    Validates progressive GraphQL fields (annotationNavigation, pageAnnotations).
    """

    def setUp(self):
        super().setUp()

        # Create a dedicated corpus
        self.corpus = Corpus.objects.create(
            title="GQL Progressive Corpus", creator=self.user
        )

        # Analyzer + Analysis for testing analysis filtering
        self.analyzer = Analyzer.objects.create(
            id="gql_progressive_analyzer",
            description="Analyzer for GraphQL progressive tests",
            creator=self.user,
            manifest={},
            task_name="test_task",
        )
        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer, analyzed_corpus=self.corpus, creator=self.user
        )

        # Label
        self.label = AnnotationLabel.objects.create(text="GQL Label", creator=self.user)

        # Dataset: 3 pages, 3 annotations per page: 1 structural + 2 non-structural
        # Mark one non-structural per page with analysis
        anns: list[Annotation] = []
        for page in [1, 2, 3]:
            # structural
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"Structural p{page}",
                    creator=self.user,
                    structural=True,
                    bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
                )
            )
            # non-structural, no analysis
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"NS no-analysis p{page}",
                    creator=self.user,
                    structural=False,
                    bounding_box={"x": 10, "y": 10, "width": 10, "height": 10},
                )
            )
            # non-structural, with analysis
            anns.append(
                Annotation(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label,
                    raw_text=f"NS with-analysis p{page}",
                    creator=self.user,
                    structural=False,
                    analysis=self.analysis,
                    bounding_box={"x": 20, "y": 20, "width": 10, "height": 10},
                )
            )

        Annotation.objects.bulk_create(anns)

        # Populate MVs so MV path is available for nav without analysis
        with connection.cursor() as cursor:
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
            )
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )

        self.client = Client(schema)
        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)
        self.analysis_gid = to_global_id("AnalysisType", self.analysis.id)

    def test_annotation_navigation_without_analysis_uses_mv(self):
        """
        When analysisId is omitted, resolver can use MV and should return only non-structural annotations.
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
        result = self.client.execute(
            query,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid},
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in result, result.get("errors")
        nav = result["data"]["document"]["annotationNavigation"]
        # 3 pages * 2 non-structural per page
        assert len(nav) == 6
        # Minimal fields present
        for item in nav:
            assert "page" in item and "boundingBox" in item and "id" in item

    def test_annotation_navigation_with_analysis_filters_direct_query(self):
        """
        With analysisId, resolver should filter and return only analyzed non-structural annotations.
        """
        query = """
        query GetNavWithAnalysis($docId: String!, $corpusId: ID!, $analysisId: ID) {
          document(id: $docId) {
            id
            annotationNavigation(corpusId: $corpusId, analysisId: $analysisId) {
              id
              page
              boundingBox
            }
          }
        }
        """
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "analysisId": self.analysis_gid,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in result, result.get("errors")
        nav = result["data"]["document"]["annotationNavigation"]
        # 3 pages * 1 analyzed non-structural each
        assert len(nav) == 3

    def test_page_annotations_structural_and_nonstructural(self):
        """
        Ensure pageAnnotations returns correct counts by structural flag.
        """
        query = """
        query PageAnn($docId: String!, $corpusId: ID!, $page: Int!, $structural: Boolean) {
          document(id: $docId) {
            id
            pageAnnotations(corpusId: $corpusId, page: $page, structural: $structural) {
              id
              page
              structural
              annotationLabel { id }
            }
          }
        }
        """
        # Structural only (1 per page)
        res_struct = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "page": 2,
                "structural": True,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res_struct, res_struct.get("errors")
        assert len(res_struct["data"]["document"]["pageAnnotations"]) == 1

        # Non-structural only (2 per page)
        res_nonstruct = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "page": 2,
                "structural": False,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )
        assert "errors" not in res_nonstruct, res_nonstruct.get("errors")
        assert len(res_nonstruct["data"]["document"]["pageAnnotations"]) == 2

