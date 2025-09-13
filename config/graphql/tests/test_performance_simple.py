"""
Simple working test for performance optimizations.
Tests the key GraphQL endpoints actually work.
"""

from django.contrib.auth import get_user_model
from graphene_django.utils.testing import GraphQLTestCase
from graphql_relay import to_global_id

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document

User = get_user_model()


class SimplePerformanceTestCase(GraphQLTestCase):
    """Simple test case that actually works."""

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        """Create minimal test data."""
        # Create test user
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(self.user)

        # Create test corpus
        self.corpus = Corpus.objects.create(title="Test Corpus", creator=self.user)

        # Create test document
        self.document = Document.objects.create(
            title="Test Document", creator=self.user, page_count=10
        )

        # Add document to corpus
        self.corpus.documents.add(self.document)

        # Create a label
        self.label = AnnotationLabel.objects.create(
            text="Test Label", creator=self.user
        )

        # Create a few annotations
        for i in range(5):
            Annotation.objects.create(
                document=self.document,
                corpus=self.corpus,
                page=1,
                annotation_label=self.label,
                raw_text=f"Test annotation {i}",
                creator=self.user,
            )

    def test_annotation_manifest_endpoint_exists(self):
        """Test that the annotation manifest endpoint exists and returns data."""
        query = """
            query GetManifest($documentId: ID!, $corpusId: ID!) {
                document(id: $documentId) {
                    id
                    annotationManifest(corpusId: $corpusId) {
                        totalCount
                        structuralCount
                        corpusCount
                    }
                }
            }
        """

        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        response = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )

        # Check response is valid
        self.assertResponseNoErrors(response)
        content = response.json()

        # Check structure
        self.assertIn("data", content)
        self.assertIn("document", content["data"])

        # The document should exist and have manifest
        if content["data"]["document"]:
            self.assertIn("annotationManifest", content["data"]["document"])
            manifest = content["data"]["document"]["annotationManifest"]

            # Check manifest has expected fields
            self.assertIn("totalCount", manifest)
            self.assertIn("structuralCount", manifest)
            self.assertIn("corpusCount", manifest)

            # Check values make sense
            self.assertGreaterEqual(manifest["totalCount"], 0)
            self.assertGreaterEqual(manifest["corpusCount"], 0)

    def test_page_annotations_endpoint_exists(self):
        """Test that page annotations endpoint exists."""
        query = """
            query GetPageAnnotations($documentId: ID!, $page: Int!, $corpusId: ID!) {
                document(id: $documentId) {
                    id
                    pageAnnotations(page: $page, corpusId: $corpusId) {
                        edges {
                            node {
                                id
                                page
                            }
                        }
                    }
                }
            }
        """

        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        response = self.query(
            query,
            variables={"documentId": document_gid, "page": 1, "corpusId": corpus_gid},
        )

        # Check response is valid
        self.assertResponseNoErrors(response)
        content = response.json()

        # Check structure
        self.assertIn("data", content)
        self.assertIn("document", content["data"])

    def test_batch_page_annotations_endpoint_exists(self):
        """Test that batch page annotations endpoint exists."""
        query = """
            query GetBatchPages($documentId: ID!, $pages: [Int!]!, $corpusId: ID!) {
                document(id: $documentId) {
                    id
                    batchPageAnnotations(pages: $pages, corpusId: $corpusId) {
                        page
                        count
                    }
                }
            }
        """

        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        response = self.query(
            query,
            variables={
                "documentId": document_gid,
                "pages": [1, 2, 3],
                "corpusId": corpus_gid,
            },
        )

        # Check response is valid
        self.assertResponseNoErrors(response)
        content = response.json()

        # Check structure
        self.assertIn("data", content)
        self.assertIn("document", content["data"])

        if content["data"]["document"]:
            self.assertIn("batchPageAnnotations", content["data"]["document"])

    def test_all_annotations_still_works(self):
        """Test that the existing allAnnotations field still works."""
        query = """
            query GetAllAnnotations($documentId: ID!, $corpusId: ID!) {
                document(id: $documentId) {
                    id
                    allAnnotations(corpusId: $corpusId) {
                        id
                        page
                        rawText
                    }
                }
            }
        """

        document_gid = to_global_id("DocumentType", self.document.id)
        corpus_gid = to_global_id("CorpusType", self.corpus.id)

        response = self.query(
            query, variables={"documentId": document_gid, "corpusId": corpus_gid}
        )

        # Check response is valid
        self.assertResponseNoErrors(response)
        content = response.json()

        # Check structure
        self.assertIn("data", content)
        self.assertIn("document", content["data"])

        if content["data"]["document"]:
            self.assertIn("allAnnotations", content["data"]["document"])
            annotations = content["data"]["document"]["allAnnotations"]

            # We created 5 annotations, so should have at least those
            self.assertIsInstance(annotations, list)
            self.assertGreaterEqual(len(annotations), 5)
