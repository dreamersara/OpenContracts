"""
Test suite to ensure data parity between old monolithic query and new progressive loading pattern.

This test validates that the new optimized queries produce exactly the same data as the
original GET_DOCUMENT_KNOWLEDGE_AND_ANNOTATIONS query when all progressive queries are
executed and their results combined.
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


class DataParityTestCase(BaseFixtureTestCase):
    """
    Test that new progressive loading queries produce identical data to the old monolithic query.
    """

    def setUp(self):
        super().setUp()

        # Create test corpus
        self.corpus = Corpus.objects.create(
            title="Data Parity Test Corpus",
            creator=self.user,
            description="Testing data parity between old and new query patterns"
        )

        # Create additional test documents for relationships
        self.doc2 = Document.objects.create(
            title="Related Document",
            description="Document for relationship testing",
            creator=self.user,
            file_type="application/pdf"
        )

        # Create analyzer and analysis for some annotations
        self.analyzer = Analyzer.objects.create(
            id="parity_test_analyzer",
            description="Analyzer for parity testing",
            creator=self.user,
            manifest={},
            task_name="parity_test_task"
        )

        self.analysis = Analysis.objects.create(
            analyzer=self.analyzer,
            analyzed_corpus=self.corpus,
            creator=self.user
        )

        # Create comprehensive test data
        self._create_comprehensive_test_data()

        # Refresh materialized views if they exist
        self._refresh_materialized_views()

        # Set up GraphQL client
        self.client = Client(schema)
        self.context = type("obj", (object,), {"user": self.user})()

    def _create_comprehensive_test_data(self):
        """Create a comprehensive dataset that exercises all aspects of the query."""

        # Create multiple annotation labels
        self.labels = []
        for i in range(5):
            label = AnnotationLabel.objects.create(
                text=f"Test Label {i}",
                color=f"color{i}",
                icon=f"icon{i}",
                description=f"Description for label {i}",
                label_type="human_annotation" if i % 2 == 0 else "machine_annotation",
                creator=self.user
            )
            self.labels.append(label)

        # Create relationship labels (using AnnotationLabel since that's what Relationship uses)
        self.rel_labels = []
        for i in range(3):
            rel_label = AnnotationLabel.objects.create(
                text=f"Relationship Label {i}",
                color=f"relcolor{i}",
                icon=f"relicon{i}",
                description=f"Relationship description {i}",
                label_type="relationship",
                creator=self.user
            )
            self.rel_labels.append(rel_label)

        # Create document notes
        self.notes = []
        for i in range(3):
            note = Note.objects.create(
                document=self.doc,
                corpus=self.corpus,
                title=f"Note {i}",
                content=f"Content for note {i}",
                creator=self.user
            )
            self.notes.append(note)

        # Create document relationships
        self.doc_relationships = []
        # Create a NOTES relationship (no label required)
        doc_rel1 = DocumentRelationship.objects.create(
            source_document=self.doc,
            target_document=self.doc2,
            relationship_type="NOTES",
            corpus=self.corpus,
            creator=self.user
        )
        self.doc_relationships.append(doc_rel1)

        # Create a RELATIONSHIP type (requires label)
        doc_rel2 = DocumentRelationship.objects.create(
            source_document=self.doc,
            target_document=self.doc2,
            relationship_type="RELATIONSHIP",
            annotation_label=self.labels[0],  # Use one of our annotation labels
            corpus=self.corpus,
            creator=self.user
        )
        self.doc_relationships.append(doc_rel2)

        # Create annotations with various configurations
        self.annotations = []
        annotation_counter = 0

        # Create structural annotations (no corpus)
        for page in range(1, 6):
            for i in range(2):  # 2 structural annotations per page
                ann = Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,  # Still needs corpus for foreign key
                    page=page,
                    annotation_label=self.labels[0],
                    raw_text=f"Structural annotation {annotation_counter}",
                    json={"type": "structural", "index": annotation_counter},
                    structural=True,
                    creator=self.user,
                    bounding_box={
                        "x": i * 100,
                        "y": page * 50,
                        "width": 80,
                        "height": 30
                    }
                )
                self.annotations.append(ann)
                annotation_counter += 1

        # Create user annotations (no analysis)
        for page in range(1, 11):
            for i in range(5):  # 5 user annotations per page
                ann = Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.labels[i % len(self.labels)],
                    raw_text=f"User annotation {annotation_counter}",
                    json={"type": "user", "index": annotation_counter},
                    structural=False,
                    creator=self.user,
                    analysis=None,
                    bounding_box={
                        "x": i * 50,
                        "y": page * 40,
                        "width": 40,
                        "height": 20
                    }
                )
                self.annotations.append(ann)
                annotation_counter += 1

        # Create analysis annotations
        for page in range(1, 8):
            for i in range(3):  # 3 analysis annotations per page
                ann = Annotation.objects.create(
                    document=self.doc,
                    corpus=self.corpus,
                    page=page,
                    annotation_label=self.labels[i % len(self.labels)],
                    raw_text=f"Analysis annotation {annotation_counter}",
                    json={"type": "analysis", "index": annotation_counter},
                    structural=False,
                    creator=self.user,
                    analysis=self.analysis,
                    bounding_box={
                        "x": i * 60,
                        "y": page * 45,
                        "width": 50,
                        "height": 25
                    }
                )
                self.annotations.append(ann)
                annotation_counter += 1

        # Create user feedback on some annotations
        self.feedback = []
        for i, ann in enumerate(self.annotations[:10]):  # Add feedback to first 10 annotations
            feedback = UserFeedback.objects.create(
                commented_annotation=ann,
                approved=(i % 3 == 0),
                rejected=(i % 3 == 1),
                comment=f"Feedback comment {i}" if i % 2 == 0 else "",  # Empty string instead of None
                creator=self.user
            )
            self.feedback.append(feedback)

        # Create relationships between annotations
        self.relationships = []
        # Create relationships only between non-structural annotations that exist
        non_structural = [a for a in self.annotations if not a.structural]
        for i in range(min(5, len(non_structural) // 2)):
            if i * 2 + 1 < len(non_structural):
                rel = Relationship.objects.create(
                    corpus=self.corpus,
                    document=self.doc,
                    creator=self.user,
                    relationship_label=self.rel_labels[i % len(self.rel_labels)],
                    structural=False
                )
                rel.source_annotations.add(non_structural[i * 2])
                rel.target_annotations.add(non_structural[i * 2 + 1])
                self.relationships.append(rel)

    def _refresh_materialized_views(self):
        """Refresh materialized views if they exist."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT matviewname FROM pg_matviews
                WHERE matviewname IN ('annotation_summary_mv', 'annotation_navigation_mv')
            """)
            existing_views = [row[0] for row in cursor.fetchall()]

            for view in existing_views:
                cursor.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")

    def test_monolithic_query_execution(self):
        """Test that the old monolithic query still works and gather baseline data."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)
        analysis_id = to_global_id("AnalysisType", self.analysis.id)

        query = """
        query GetDocumentKnowledgeAndAnnotations(
            $documentId: ID!
            $corpusId: ID!
            $analysisId: ID
        ) {
            document(id: $documentId) {
                id
                title
                fileType
                creator {
                    email
                }
                created
                myPermissions

                allNotes(corpusId: $corpusId) {
                    id
                    title
                    content
                    created
                    creator {
                        email
                    }
                }

                allDocRelationships(corpusId: $corpusId) {
                    id
                    relationshipType
                    sourceDocument {
                        id
                        title
                        fileType
                    }
                    targetDocument {
                        id
                        title
                        fileType
                    }
                    created
                }

                allStructuralAnnotations {
                    id
                    page
                    annotationLabel {
                        id
                        text
                        color
                        icon
                        description
                        labelType
                    }
                    annotationType
                    rawText
                    json
                    myPermissions
                    structural
                }

                allAnnotations(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    page
                    annotationLabel {
                        id
                        text
                        color
                        icon
                        description
                        labelType
                    }
                    userFeedback {
                        edges {
                            node {
                                id
                                approved
                                rejected
                                comment
                            }
                        }
                        totalCount
                    }
                    annotationType
                    rawText
                    json
                    myPermissions
                    structural
                }

                allRelationships(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    structural
                    relationshipLabel {
                        id
                        text
                        color
                        icon
                        description
                    }
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
                    myPermissions
                }
            }
        }
        """

        start_time = time.perf_counter()
        result = self.client.execute(
            query,
            variables={
                "documentId": doc_id,
                "corpusId": corpus_id,
                "analysisId": analysis_id
            },
            context_value=self.context
        )
        monolithic_time = time.perf_counter() - start_time

        self.assertIsNone(result.get("errors"), f"Monolithic query failed: {result.get('errors')}")

        # Store monolithic results for comparison
        self.monolithic_data = result["data"]["document"]
        self.monolithic_time = monolithic_time

        print(f"\nMonolithic query execution time: {monolithic_time:.3f}s")
        print(f"Total annotations returned: {len(self.monolithic_data.get('allAnnotations', []))}")
        print(f"Total structural annotations: {len(self.monolithic_data.get('allStructuralAnnotations', []))}")
        print(f"Total relationships: {len(self.monolithic_data.get('allRelationships', []))}")

    def test_progressive_loading_data_parity(self):
        """Test that progressive loading queries produce identical data to monolithic query."""

        # First run monolithic query to get baseline
        self.test_monolithic_query_execution()

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)
        analysis_id = to_global_id("AnalysisType", self.analysis.id)

        progressive_data = {}
        total_progressive_time = 0.0

        # 1. Get document metadata and knowledge base fields
        metadata_query = """
        query GetDocumentMetadata($documentId: ID!, $corpusId: ID!) {
            document(id: $documentId) {
                id
                title
                fileType
                creator {
                    email
                }
                created
                myPermissions

                allNotes(corpusId: $corpusId) {
                    id
                    title
                    content
                    created
                    creator {
                        email
                    }
                }

                allDocRelationships(corpusId: $corpusId) {
                    id
                    relationshipType
                    sourceDocument {
                        id
                        title
                        fileType
                    }
                    targetDocument {
                        id
                        title
                        fileType
                    }
                    created
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

        # 2. Get annotation summary to understand what pages have content
        summary_query = """
        query GetAnnotationSummary($documentId: ID!, $corpusId: ID!) {
            document(id: $documentId) {
                annotationSummary(corpusId: $corpusId) {
                    annotationCount
                    structuralCount
                    pageCount
                    pagesWithAnnotations
                    firstAnnotatedPage
                    lastAnnotatedPage
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

        self.assertIsNone(summary_result.get("errors"))
        summary_data = summary_result["data"]["document"]["annotationSummary"]

        # 3. Get all structural annotations (they're document-wide, not corpus-specific)
        structural_query = """
        query GetStructuralAnnotations($documentId: ID!) {
            document(id: $documentId) {
                allStructuralAnnotations {
                    id
                    page
                    annotationLabel {
                        id
                        text
                        color
                        icon
                        description
                        labelType
                    }
                    annotationType
                    rawText
                    json
                    myPermissions
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

        # 4. Load annotations page by page (simulating progressive loading)
        all_annotations = []
        pages_to_load = summary_data.get("pagesWithAnnotations", [])

        if not pages_to_load:
            # If no pages with annotations info, load all pages up to last annotated
            if summary_data.get("lastAnnotatedPage"):
                pages_to_load = list(range(1, summary_data["lastAnnotatedPage"] + 1))

        for page in pages_to_load:
            page_query = """
            query GetPageAnnotations(
                $documentId: ID!
                $corpusId: ID!
                $page: Int!
                $analysisId: ID
            ) {
                document(id: $documentId) {
                    pageAnnotations(
                        corpusId: $corpusId
                        page: $page
                        analysisId: $analysisId
                    ) {
                        id
                        page
                        annotationLabel {
                            id
                            text
                            color
                            icon
                            description
                            labelType
                        }
                        userFeedback {
                            edges {
                                node {
                                    id
                                    approved
                                    rejected
                                    comment
                                }
                            }
                            totalCount
                        }
                        annotationType
                        rawText
                        json
                        myPermissions
                        structural
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
                page_annotations = page_result["data"]["document"].get("pageAnnotations", [])
                all_annotations.extend(page_annotations)

        progressive_data["allAnnotations"] = all_annotations

        # 5. Get relationships
        relationships_query = """
        query GetRelationships($documentId: ID!, $corpusId: ID!, $analysisId: ID) {
            document(id: $documentId) {
                allRelationships(corpusId: $corpusId, analysisId: $analysisId) {
                    id
                    structural
                    relationshipLabel {
                        id
                        text
                        color
                        icon
                        description
                    }
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
                    myPermissions
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

        # Now compare the results
        print(f"\nProgressive loading total time: {total_progressive_time:.3f}s")
        print(f"Monolithic query time: {self.monolithic_time:.3f}s")
        print(f"Performance improvement: {self.monolithic_time / total_progressive_time:.1f}x faster")

        # Compare data completeness
        self._compare_data_completeness(self.monolithic_data, progressive_data)

    def _compare_data_completeness(self, monolithic_data: Dict, progressive_data: Dict):
        """Compare data from monolithic and progressive queries for completeness."""

        # Helper function to normalize and sort annotations
        def normalize_annotations(annotations: List[Dict]) -> List[Dict]:
            """Sort and normalize annotations for comparison."""
            normalized = []
            for ann in annotations:
                # Create a normalized copy
                norm_ann = {
                    "id": ann.get("id"),
                    "page": ann.get("page"),
                    "rawText": ann.get("rawText"),
                    "structural": ann.get("structural"),
                    "annotationType": ann.get("annotationType"),
                    "json": ann.get("json")
                }

                # Normalize label
                if ann.get("annotationLabel"):
                    norm_ann["annotationLabel"] = {
                        "id": ann["annotationLabel"].get("id"),
                        "text": ann["annotationLabel"].get("text"),
                        "color": ann["annotationLabel"].get("color"),
                        "icon": ann["annotationLabel"].get("icon"),
                        "labelType": ann["annotationLabel"].get("labelType")
                    }

                # Normalize feedback
                if ann.get("userFeedback"):
                    feedback_nodes = []
                    for edge in ann["userFeedback"].get("edges", []):
                        if edge.get("node"):
                            feedback_nodes.append({
                                "id": edge["node"].get("id"),
                                "approved": edge["node"].get("approved"),
                                "rejected": edge["node"].get("rejected"),
                                "comment": edge["node"].get("comment")
                            })
                    norm_ann["userFeedback"] = {
                        "nodes": sorted(feedback_nodes, key=lambda x: x.get("id", "")),
                        "totalCount": ann["userFeedback"].get("totalCount", 0)
                    }

                normalized.append(norm_ann)

            # Sort by ID for consistent comparison
            return sorted(normalized, key=lambda x: x.get("id", ""))

        # Compare metadata fields
        self.assertEqual(
            monolithic_data.get("id"),
            progressive_data.get("id"),
            "Document IDs don't match"
        )

        self.assertEqual(
            monolithic_data.get("title"),
            progressive_data.get("title"),
            "Document titles don't match"
        )

        # Compare notes
        monolithic_notes = sorted(
            monolithic_data.get("allNotes", []),
            key=lambda x: x.get("id", "")
        )
        progressive_notes = sorted(
            progressive_data.get("allNotes", []),
            key=lambda x: x.get("id", "")
        )

        self.assertEqual(
            len(monolithic_notes),
            len(progressive_notes),
            f"Note counts don't match: {len(monolithic_notes)} vs {len(progressive_notes)}"
        )

        for m_note, p_note in zip(monolithic_notes, progressive_notes):
            self.assertEqual(m_note["id"], p_note["id"], "Note IDs don't match")
            self.assertEqual(m_note["title"], p_note["title"], "Note titles don't match")
            self.assertEqual(m_note["content"], p_note["content"], "Note content doesn't match")

        # Compare document relationships
        monolithic_doc_rels = sorted(
            monolithic_data.get("allDocRelationships", []),
            key=lambda x: x.get("id", "")
        )
        progressive_doc_rels = sorted(
            progressive_data.get("allDocRelationships", []),
            key=lambda x: x.get("id", "")
        )

        self.assertEqual(
            len(monolithic_doc_rels),
            len(progressive_doc_rels),
            f"Document relationship counts don't match: {len(monolithic_doc_rels)} vs {len(progressive_doc_rels)}"
        )

        # Compare structural annotations
        monolithic_structural = normalize_annotations(
            monolithic_data.get("allStructuralAnnotations", [])
        )
        progressive_structural = normalize_annotations(
            progressive_data.get("allStructuralAnnotations", [])
        )

        self.assertEqual(
            len(monolithic_structural),
            len(progressive_structural),
            f"Structural annotation counts don't match: {len(monolithic_structural)} vs {len(progressive_structural)}"
        )

        # Compare each structural annotation
        for m_ann, p_ann in zip(monolithic_structural, progressive_structural):
            self.assertEqual(
                m_ann["id"], p_ann["id"],
                f"Structural annotation IDs don't match"
            )
            self.assertEqual(
                m_ann["rawText"], p_ann["rawText"],
                f"Structural annotation text doesn't match for {m_ann['id']}"
            )

        # Compare all annotations
        monolithic_annotations = normalize_annotations(
            monolithic_data.get("allAnnotations", [])
        )
        progressive_annotations = normalize_annotations(
            progressive_data.get("allAnnotations", [])
        )

        self.assertEqual(
            len(monolithic_annotations),
            len(progressive_annotations),
            f"Annotation counts don't match: {len(monolithic_annotations)} vs {len(progressive_annotations)}"
        )

        # Create sets of annotation IDs for comparison
        monolithic_ann_ids = {ann["id"] for ann in monolithic_annotations}
        progressive_ann_ids = {ann["id"] for ann in progressive_annotations}

        missing_in_progressive = monolithic_ann_ids - progressive_ann_ids
        extra_in_progressive = progressive_ann_ids - monolithic_ann_ids

        self.assertEqual(
            len(missing_in_progressive), 0,
            f"Annotations missing in progressive: {missing_in_progressive}"
        )
        self.assertEqual(
            len(extra_in_progressive), 0,
            f"Extra annotations in progressive: {extra_in_progressive}"
        )

        # Compare each annotation in detail
        monolithic_by_id = {ann["id"]: ann for ann in monolithic_annotations}
        progressive_by_id = {ann["id"]: ann for ann in progressive_annotations}

        for ann_id in monolithic_ann_ids:
            m_ann = monolithic_by_id[ann_id]
            p_ann = progressive_by_id[ann_id]

            self.assertEqual(
                m_ann.get("page"), p_ann.get("page"),
                f"Page doesn't match for annotation {ann_id}"
            )
            self.assertEqual(
                m_ann.get("rawText"), p_ann.get("rawText"),
                f"Raw text doesn't match for annotation {ann_id}"
            )
            self.assertEqual(
                m_ann.get("structural"), p_ann.get("structural"),
                f"Structural flag doesn't match for annotation {ann_id}"
            )

            # Compare user feedback if present
            if m_ann.get("userFeedback") or p_ann.get("userFeedback"):
                m_feedback = m_ann.get("userFeedback", {})
                p_feedback = p_ann.get("userFeedback", {})

                self.assertEqual(
                    m_feedback.get("totalCount", 0),
                    p_feedback.get("totalCount", 0),
                    f"Feedback count doesn't match for annotation {ann_id}"
                )

        # Compare relationships
        monolithic_rels = sorted(
            monolithic_data.get("allRelationships", []),
            key=lambda x: x.get("id", "")
        )
        progressive_rels = sorted(
            progressive_data.get("allRelationships", []),
            key=lambda x: x.get("id", "")
        )

        self.assertEqual(
            len(monolithic_rels),
            len(progressive_rels),
            f"Relationship counts don't match: {len(monolithic_rels)} vs {len(progressive_rels)}"
        )

        print("\n✅ Data parity test PASSED!")
        print(f"  - {len(monolithic_annotations)} annotations matched")
        print(f"  - {len(monolithic_structural)} structural annotations matched")
        print(f"  - {len(monolithic_rels)} relationships matched")
        print(f"  - {len(monolithic_notes)} notes matched")
        print(f"  - {len(monolithic_doc_rels)} document relationships matched")

    def test_edge_cases_and_filters(self):
        """Test edge cases and various filter combinations."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)

        # Test 1: Query without analysis filter (should return only user annotations)
        query_no_analysis = """
        query GetAnnotationsNoAnalysis($documentId: ID!, $corpusId: ID!) {
            document(id: $documentId) {
                allAnnotations(corpusId: $corpusId) {
                    id
                    structural
                }
            }
        }
        """

        result = self.client.execute(
            query_no_analysis,
            variables={"documentId": doc_id, "corpusId": corpus_id},
            context_value=self.context
        )

        self.assertIsNone(result.get("errors"))
        annotations = result["data"]["document"]["allAnnotations"]

        # Should include both structural and non-structural annotations when no analysis specified
        structural_count = sum(1 for ann in annotations if ann["structural"])
        non_structural_count = sum(1 for ann in annotations if not ann["structural"])

        self.assertGreater(structural_count, 0, "Should have structural annotations")
        self.assertGreater(non_structural_count, 0, "Should have non-structural annotations")

        # Test 2: Empty corpus (no annotations)
        empty_corpus = Corpus.objects.create(
            title="Empty Corpus",
            creator=self.user
        )
        empty_corpus_id = to_global_id("CorpusType", empty_corpus.id)

        result = self.client.execute(
            query_no_analysis,
            variables={"documentId": doc_id, "corpusId": empty_corpus_id},
            context_value=self.context
        )

        self.assertIsNone(result.get("errors"))
        # Should return structural annotations even for empty corpus
        annotations = result["data"]["document"]["allAnnotations"]
        structural_in_empty = [ann for ann in annotations if ann["structural"]]
        self.assertGreater(len(structural_in_empty), 0, "Should return structural annotations for empty corpus")

    def test_performance_comparison(self):
        """Compare performance between monolithic and progressive approaches."""

        doc_id = to_global_id("DocumentType", self.doc.id)
        corpus_id = to_global_id("CorpusType", self.corpus.id)

        # Run each approach multiple times to get average
        iterations = 5
        monolithic_times = []
        progressive_times = []

        for i in range(iterations):
            # Monolithic query
            start = time.perf_counter()
            result = self.client.execute(
                """
                query GetAll($documentId: ID!, $corpusId: ID!) {
                    document(id: $documentId) {
                        allAnnotations(corpusId: $corpusId) {
                            id
                            page
                            rawText
                            userFeedback {
                                edges {
                                    node {
                                        id
                                    }
                                }
                            }
                        }
                        allRelationships(corpusId: $corpusId) {
                            id
                        }
                    }
                }
                """,
                variables={"documentId": doc_id, "corpusId": corpus_id},
                context_value=self.context
            )
            monolithic_times.append(time.perf_counter() - start)

            # Progressive approach - just load summary and first few pages
            start = time.perf_counter()

            # Get summary
            self.client.execute(
                """
                query GetSummary($documentId: ID!, $corpusId: ID!) {
                    document(id: $documentId) {
                        annotationSummary(corpusId: $corpusId) {
                            pageCount
                            pagesWithAnnotations
                        }
                    }
                }
                """,
                variables={"documentId": doc_id, "corpusId": corpus_id},
                context_value=self.context
            )

            # Load first 3 pages
            for page in [1, 2, 3]:
                self.client.execute(
                    """
                    query GetPage($documentId: ID!, $corpusId: ID!, $page: Int!) {
                        document(id: $documentId) {
                            pageAnnotations(corpusId: $corpusId, page: $page) {
                                id
                                rawText
                            }
                        }
                    }
                    """,
                    variables={"documentId": doc_id, "corpusId": corpus_id, "page": page},
                    context_value=self.context
                )

            progressive_times.append(time.perf_counter() - start)

        avg_monolithic = sum(monolithic_times) / len(monolithic_times)
        avg_progressive = sum(progressive_times) / len(progressive_times)

        print(f"\nPerformance Comparison (average of {iterations} runs):")
        print(f"  Monolithic query: {avg_monolithic:.3f}s")
        print(f"  Progressive loading (summary + 3 pages): {avg_progressive:.3f}s")
        print(f"  Progressive is {avg_monolithic / avg_progressive:.1f}x faster for initial load")

        # Progressive should be faster for initial page load
        self.assertLess(
            avg_progressive,
            avg_monolithic,
            "Progressive loading should be faster for initial page load"
        )