"""
Debug test to understand the data parity issue.
"""

from django.contrib.auth import get_user_model
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.analyzer.models import Analysis, Analyzer
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tests.base import BaseFixtureTestCase

User = get_user_model()


class DebugParityTestCase(BaseFixtureTestCase):
    """Debug test to understand data parity issues."""

    def setUp(self):
        super().setUp()

        # Create test corpus
        self.corpus = Corpus.objects.create(
            title="Debug Test Corpus",
            creator=self.user
        )

        # Create analyzer and analysis
        self.analyzer = Analyzer.objects.create(
            id="debug_analyzer",
            description="Debug analyzer",
            creator=self.user,
            manifest={},
            task_name="debug_task"
        )

        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer,
            analyzed_corpus=self.corpus,
            creator=self.user
        )

        # Create label
        self.label = AnnotationLabel.objects.create(
            text="Debug Label",
            creator=self.user
        )

        # Create simple annotations
        # 2 structural annotations
        for i in range(2):
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=i+1,
                annotation_label=self.label,
                raw_text=f"Structural {i}",
                structural=True,
                creator=self.user
            )

        # 3 user annotations (no analysis)
        for i in range(3):
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=1,
                annotation_label=self.label,
                raw_text=f"User ann {i}",
                structural=False,
                analysis=None,
                creator=self.user
            )

        # 2 analysis annotations
        for i in range(2):
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=2,
                annotation_label=self.label,
                raw_text=f"Analysis ann {i}",
                structural=False,
                analysis=self.analysis,
                creator=self.user
            )

        self.client = Client(schema)
        self.context = type("obj", (object,), {"user": self.user})()

    def test_debug_queries(self):
        """Debug what each query returns."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)
        analysis_id = to_global_id("AnalysisType", self.analysis.id)

        print(f"\n{'='*60}")
        print("DATABASE STATE")
        print(f"{'='*60}")

        # Check database directly
        all_anns = Annotation.objects.filter(document=self.doc)
        structural = all_anns.filter(structural=True)
        non_structural = all_anns.filter(structural=False)
        user_anns = non_structural.filter(analysis__isnull=True)
        analysis_anns = non_structural.filter(analysis=self.analysis)

        print(f"Total annotations in DB: {all_anns.count()}")
        print(f"  - Structural: {structural.count()}")
        print(f"  - Non-structural: {non_structural.count()}")
        print(f"    - User annotations: {user_anns.count()}")
        print(f"    - Analysis annotations: {analysis_anns.count()}")

        print(f"\n{'='*60}")
        print("GRAPHQL QUERIES")
        print(f"{'='*60}")

        # Test 1: allStructuralAnnotations
        query1 = """
        query Test1($documentId: String!) {
            document(id: $documentId) {
                allStructuralAnnotations {
                    id
                    structural
                    rawText
                }
            }
        }
        """

        result1 = self.client.execute(
            query1,
            variables={"documentId": doc_id},
            context_value=self.context
        )

        if result1.get("errors"):
            print(f"Error in query1: {result1['errors']}")
        else:
            structural_anns = result1["data"]["document"]["allStructuralAnnotations"]
            print(f"\nallStructuralAnnotations returned: {len(structural_anns)}")
            for ann in structural_anns[:5]:  # Show first 5
                print(f"  - {ann['rawText']} (structural={ann['structural']})")

        # Test 2: allAnnotations with NO analysis filter
        query2 = """
        query Test2($documentId: String!, $corpusId: ID!) {
            document(id: $documentId) {
                allAnnotations(corpusId: $corpusId) {
                    id
                    structural
                    rawText
                }
            }
        }
        """

        result2 = self.client.execute(
            query2,
            variables={"documentId": doc_id, "corpusId": corpus_id},
            context_value=self.context
        )

        if result2.get("errors"):
            print(f"Error in query2: {result2['errors']}")
        else:
            all_anns_no_analysis = result2["data"]["document"]["allAnnotations"]
            print(f"\nallAnnotations (NO analysis filter) returned: {len(all_anns_no_analysis)}")
            for ann in all_anns_no_analysis[:5]:  # Show first 5
                print(f"  - {ann['rawText']} (structural={ann['structural']})")

        # Test 3: allAnnotations WITH analysis filter
        query3 = """
        query Test3($documentId: String!, $corpusId: ID!, $analysisId: ID) {
            document(id: $documentId) {
                allAnnotations(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    structural
                    rawText
                }
            }
        }
        """

        result3 = self.client.execute(
            query3,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "analysisId": analysis_id
            },
            context_value=self.context
        )

        if result3.get("errors"):
            print(f"Error in query3: {result3['errors']}")
        else:
            all_anns_with_analysis = result3["data"]["document"]["allAnnotations"]
            print(f"\nallAnnotations (WITH analysis={analysis_id}) returned: {len(all_anns_with_analysis)}")
            for ann in all_anns_with_analysis[:5]:  # Show first 5
                print(f"  - {ann['rawText']} (structural={ann['structural']})")

        # Test 4: pageAnnotations
        query4 = """
        query Test4($documentId: String!, $corpusId: ID!, $page: Int!, $analysisId: ID) {
            document(id: $documentId) {
                pageAnnotations(corpusId: $corpusId, page: $page, analysisId: $analysisId) {
                    id
                    structural
                    rawText
                }
            }
        }
        """

        # Test page 1
        result4_p1 = self.client.execute(
            query4,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "page": 1,
                "analysisId": analysis_id
            },
            context_value=self.context
        )

        # Test page 2
        result4_p2 = self.client.execute(
            query4,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "page": 2,
                "analysisId": analysis_id
            },
            context_value=self.context
        )

        if result4_p1.get("data") and result4_p2.get("data"):
            page1_anns = result4_p1["data"]["document"]["pageAnnotations"]
            page2_anns = result4_p2["data"]["document"]["pageAnnotations"]
            print(f"\npageAnnotations (page 1) returned: {len(page1_anns)}")
            for ann in page1_anns:
                print(f"  - {ann['rawText']} (structural={ann['structural']})")
            print(f"\npageAnnotations (page 2) returned: {len(page2_anns)}")
            for ann in page2_anns:
                print(f"  - {ann['rawText']} (structural={ann['structural']})")

        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print("\nExpected behavior:")
        print("- allStructuralAnnotations: Should return 2 structural annotations")
        print("- allAnnotations (no analysis): Should return structural + user annotations = 5")
        print("- allAnnotations (with analysis): Should return structural + analysis annotations = 4")
        print("- pageAnnotations: Should return annotations for specific page based on filters")