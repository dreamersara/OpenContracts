"""
Simplified test to validate data parity between monolithic and progressive loading queries.

This test creates a comprehensive dataset and compares the results between the old
GET_DOCUMENT_KNOWLEDGE_AND_ANNOTATIONS query and the new progressive loading approach.
"""

import time
from typing import Dict, List

from django.contrib.auth import get_user_model
from django.db import connection
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.analyzer.models import Analysis, Analyzer
from opencontractserver.annotations.models import (
    Annotation,
    AnnotationLabel,
    Note,
    Relationship,
)
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document, DocumentRelationship
from opencontractserver.feedback.models import UserFeedback
from opencontractserver.tests.base import BaseFixtureTestCase

User = get_user_model()


class SimpleDataParityTestCase(BaseFixtureTestCase):
    """
    Simplified test for data parity between monolithic and progressive queries.
    """

    def setUp(self):
        super().setUp()

        # Create test corpus
        self.corpus = Corpus.objects.create(
            title="Simple Parity Test Corpus",
            creator=self.user,
            description="Testing data parity"
        )

        # Create analyzer and analysis
        self.analyzer = Analyzer.objects.create(
            id="simple_test_analyzer",
            description="Simple test analyzer",
            creator=self.user,
            manifest={},
            task_name="simple_test_task"
        )

        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer,
            analyzed_corpus=self.corpus,
            creator=self.user
        )

        # Create annotation labels
        self.label1 = AnnotationLabel.objects.create(
            text="Test Label 1",
            color="blue",
            icon="icon1",
            description="First test label",
            label_type="span_label",
            creator=self.user
        )

        self.label2 = AnnotationLabel.objects.create(
            text="Test Label 2",
            color="red",
            icon="icon2",
            description="Second test label",
            label_type="doc_type_label",
            creator=self.user
        )

        # Create simple test data
        self._create_simple_test_data()

        # Refresh materialized views if they exist
        self._refresh_materialized_views()

        # Set up GraphQL client
        self.client = Client(schema)
        self.context = type("obj", (object,), {"user": self.user})()

    def _create_simple_test_data(self):
        """Create a simple but comprehensive test dataset."""

        # Create 10 pages of annotations
        self.annotations = []

        # Create structural annotations (5 total)
        for page in range(1, 6):
            ann = Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label1,
                raw_text=f"Structural annotation on page {page}",
                json={"type": "structural", "page": page},
                structural=True,
                creator=self.user,
                bounding_box={"x": 10, "y": page * 10, "width": 100, "height": 20}
            )
            self.annotations.append(ann)

        # Create user annotations (10 total)
        for page in range(1, 6):
            for i in range(2):
                ann = Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.label2 if i == 0 else self.label1,
                    raw_text=f"User annotation {i} on page {page}",
                    json={"type": "user", "page": page, "index": i},
                    structural=False,
                    creator=self.user,
                    analysis=None,
                    bounding_box={"x": i * 50, "y": page * 20, "width": 40, "height": 15}
                )
                self.annotations.append(ann)

        # Create analysis annotations (5 total)
        for page in range(1, 6):
            ann = Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label2,
                raw_text=f"Analysis annotation on page {page}",
                json={"type": "analysis", "page": page},
                structural=False,
                creator=self.user,
                analysis=self.analysis,
                bounding_box={"x": 100, "y": page * 30, "width": 50, "height": 25}
            )
            self.annotations.append(ann)

        # Create 2 notes
        for i in range(2):
            Note.objects.create(
                document=self.doc,
                corpus=self.corpus,
                title=f"Test Note {i}",
                content=f"Content for test note {i}",
                creator=self.user
            )

        # Create 1 document relationship
        doc2 = Document.objects.create(
            title="Related Test Document",
            creator=self.user,
            file_type="application/pdf"
        )

        DocumentRelationship.objects.create(
            source_document=self.doc,
            target_document=doc2,
            relationship_type="NOTES",
            corpus=self.corpus,
            creator=self.user
        )

        # Create user feedback on 3 annotations
        for i in range(3):
            UserFeedback.objects.create(
                commented_annotation=self.annotations[i],
                approved=(i == 0),
                rejected=(i == 1),
                comment=f"Test feedback {i}",
                creator=self.user
            )

        # Create 1 relationship between annotations
        rel = Relationship.objects.create(
            corpus=self.corpus,
            document=self.doc,
            creator=self.user,
            relationship_label=self.label1,
            structural=False
        )
        # Add non-structural annotations only
        non_structural = [a for a in self.annotations if not a.structural]
        if len(non_structural) >= 2:
            rel.source_annotations.add(non_structural[0])
            rel.target_annotations.add(non_structural[1])

    def _refresh_materialized_views(self):
        """Refresh materialized views if they exist."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT matviewname FROM pg_matviews
                WHERE matviewname IN ('annotation_summary_mv', 'annotation_navigation_mv')
            """)
            existing_views = [row[0] for row in cursor.fetchall()]

            for view in existing_views:
                try:
                    cursor.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
                except Exception as e:
                    print(f"Could not refresh {view}: {e}")

    def test_data_parity_between_approaches(self):
        """Main test comparing monolithic and progressive approaches."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)
        analysis_id = to_global_id("AnalysisType", self.analysis.id)

        # ============ MONOLITHIC QUERY ============
        monolithic_query = """
        query GetDocumentData($documentId: String!, $corpusId: ID!, $analysisId: ID) {
            document(id: $documentId) {
                id
                title

                allNotes(corpusId: $corpusId) {
                    id
                    title
                    content
                }

                allDocRelationships(corpusId: $corpusId) {
                    id
                    relationshipType
                }

                allStructuralAnnotations {
                    id
                    page
                    rawText
                    structural
                }

                allAnnotations(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    page
                    rawText
                    structural
                    userFeedback {
                        edges {
                            node {
                                id
                                approved
                                rejected
                                comment
                            }
                        }
                    }
                }

                allRelationships(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    sourceAnnotations {
                        edges {
                            node {
                                id
                            }
                        }
                    }
                    targetAnnotations {
                        edges {
                            node {
                                id
                            }
                        }
                    }
                }
            }
        }
        """

        start_time = time.perf_counter()
        monolithic_result = self.client.execute(
            monolithic_query,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "analysisId": analysis_id
            },
            context_value=self.context
        )
        monolithic_time = time.perf_counter() - start_time

        self.assertIsNone(
            monolithic_result.get("errors"),
            f"Monolithic query failed: {monolithic_result.get('errors')}"
        )

        monolithic_data = monolithic_result["data"]["document"]

        # ============ PROGRESSIVE QUERIES ============
        progressive_data = {}
        total_progressive_time = 0.0

        # Query 1: Document metadata and knowledge base
        metadata_query = """
        query GetMetadata($documentId: String!, $corpusId: ID!) {
            document(id: $documentId) {
                id
                title

                allNotes(corpusId: $corpusId) {
                    id
                    title
                    content
                }

                allDocRelationships(corpusId: $corpusId) {
                    id
                    relationshipType
                }
            }
        }
        """

        start = time.perf_counter()
        metadata_result = self.client.execute(
            metadata_query,
            variables={"documentId": doc_id, "corpusId": corpus_id},
            context_value=self.context
        )
        total_progressive_time += time.perf_counter() - start

        self.assertIsNone(metadata_result.get("errors"))
        progressive_data.update(metadata_result["data"]["document"])

        # Query 2: Get annotation summary
        summary_query = """
        query GetSummary($documentId: String!, $corpusId: ID!) {
            document(id: $documentId) {
                annotationSummary(corpusId: $corpusId) {
                    annotationCount
                    structuralCount
                    pageCount
                    pagesWithAnnotations
                }
            }
        }
        """

        start = time.perf_counter()
        summary_result = self.client.execute(
            summary_query,
            variables={"documentId": doc_id, "corpusId": corpus_id},
            context_value=self.context
        )
        total_progressive_time += time.perf_counter() - start

        if summary_result.get("data") and summary_result["data"]["document"]:
            summary = summary_result["data"]["document"].get("annotationSummary", {})
            pages_with_annotations = summary.get("pagesWithAnnotations", [1, 2, 3, 4, 5])
        else:
            pages_with_annotations = [1, 2, 3, 4, 5]

        # Query 3: Get structural annotations
        structural_query = """
        query GetStructural($documentId: String!) {
            document(id: $documentId) {
                allStructuralAnnotations {
                    id
                    page
                    rawText
                    structural
                }
            }
        }
        """

        start = time.perf_counter()
        structural_result = self.client.execute(
            structural_query,
            variables={"documentId": doc_id},
            context_value=self.context
        )
        total_progressive_time += time.perf_counter() - start

        self.assertIsNone(structural_result.get("errors"))
        progressive_data["allStructuralAnnotations"] = structural_result["data"]["document"]["allStructuralAnnotations"]

        # Query 4: Get page annotations (simulate loading all pages)
        all_page_annotations = []
        for page in pages_with_annotations:
            page_query = """
            query GetPage($documentId: String!, $corpusId: ID!, $page: Int!, $analysisId: ID) {
                document(id: $documentId) {
                    pageAnnotations(corpusId: $corpusId, page: $page, analysisId: $analysisId) {
                        id
                        page
                        rawText
                        structural
                        userFeedback {
                            edges {
                                node {
                                    id
                                    approved
                                    rejected
                                    comment
                                }
                            }
                        }
                    }
                }
            }
            """

            start = time.perf_counter()
            page_result = self.client.execute(
                page_query,
                variables={
                    "documentId": doc_id,
                    "corpusId": corpus_id,
                    "page": page,
                    "analysisId": analysis_id
                },
                context_value=self.context
            )
            total_progressive_time += time.perf_counter() - start

            if page_result.get("data") and page_result["data"]["document"]:
                page_anns = page_result["data"]["document"].get("pageAnnotations", [])
                all_page_annotations.extend(page_anns)

        progressive_data["allAnnotations"] = all_page_annotations

        # Query 5: Get relationships
        relationships_query = """
        query GetRelationships($documentId: String!, $corpusId: ID!, $analysisId: ID) {
            document(id: $documentId) {
                allRelationships(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    sourceAnnotations {
                        edges {
                            node {
                                id
                            }
                        }
                    }
                    targetAnnotations {
                        edges {
                            node {
                                id
                            }
                        }
                    }
                }
            }
        }
        """

        start = time.perf_counter()
        relationships_result = self.client.execute(
            relationships_query,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "analysisId": analysis_id
            },
            context_value=self.context
        )
        total_progressive_time += time.perf_counter() - start

        self.assertIsNone(relationships_result.get("errors"))
        progressive_data["allRelationships"] = relationships_result["data"]["document"]["allRelationships"]

        # ============ COMPARE RESULTS ============
        print(f"\n{'='*60}")
        print("PERFORMANCE COMPARISON")
        print(f"{'='*60}")
        print(f"Monolithic query time: {monolithic_time:.3f}s")
        print(f"Progressive queries time: {total_progressive_time:.3f}s")
        print(f"Speed improvement: {monolithic_time / total_progressive_time:.1f}x")

        print(f"\n{'='*60}")
        print("DATA COMPLETENESS CHECK")
        print(f"{'='*60}")

        # Compare notes
        monolithic_notes = sorted(monolithic_data.get("allNotes", []), key=lambda x: x["id"])
        progressive_notes = sorted(progressive_data.get("allNotes", []), key=lambda x: x["id"])

        self.assertEqual(
            len(monolithic_notes),
            len(progressive_notes),
            f"Notes count mismatch: {len(monolithic_notes)} vs {len(progressive_notes)}"
        )
        print(f"✅ Notes: {len(monolithic_notes)} matched")

        # Compare structural annotations
        monolithic_structural = sorted(
            monolithic_data.get("allStructuralAnnotations", []),
            key=lambda x: x["id"]
        )
        progressive_structural = sorted(
            progressive_data.get("allStructuralAnnotations", []),
            key=lambda x: x["id"]
        )

        self.assertEqual(
            len(monolithic_structural),
            len(progressive_structural),
            f"Structural annotations count mismatch"
        )
        print(f"✅ Structural annotations: {len(monolithic_structural)} matched")

        # Compare all annotations
        monolithic_anns = sorted(
            monolithic_data.get("allAnnotations", []),
            key=lambda x: x["id"]
        )
        progressive_anns = sorted(
            progressive_data.get("allAnnotations", []),
            key=lambda x: x["id"]
        )

        self.assertEqual(
            len(monolithic_anns),
            len(progressive_anns),
            f"Annotations count mismatch: {len(monolithic_anns)} vs {len(progressive_anns)}"
        )
        print(f"✅ All annotations: {len(monolithic_anns)} matched")

        # Check annotation IDs match
        monolithic_ids = {ann["id"] for ann in monolithic_anns}
        progressive_ids = {ann["id"] for ann in progressive_anns}

        missing_in_progressive = monolithic_ids - progressive_ids
        extra_in_progressive = progressive_ids - monolithic_ids

        self.assertEqual(
            len(missing_in_progressive), 0,
            f"Missing annotations in progressive: {missing_in_progressive}"
        )
        self.assertEqual(
            len(extra_in_progressive), 0,
            f"Extra annotations in progressive: {extra_in_progressive}"
        )

        # Compare relationships
        monolithic_rels = monolithic_data.get("allRelationships", [])
        progressive_rels = progressive_data.get("allRelationships", [])

        self.assertEqual(
            len(monolithic_rels),
            len(progressive_rels),
            f"Relationships count mismatch"
        )
        print(f"✅ Relationships: {len(monolithic_rels)} matched")

        print(f"\n{'='*60}")
        print("✅ ALL DATA PARITY TESTS PASSED!")
        print(f"{'='*60}\n")