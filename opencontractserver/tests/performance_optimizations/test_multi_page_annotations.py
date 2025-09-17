"""
Test multi-page annotations functionality.
"""

from django.test import TestCase
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.users.models import User


class MultiPageAnnotationsTest(TestCase):
    """Test the new multi-page pageAnnotations functionality."""

    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

        # Create test document
        self.doc = Document.objects.create(
            title="Test Document",
            creator=self.user,
            file_type="application/pdf",
            pdf_file="test.pdf",
        )

        # Create test corpus
        self.corpus = Corpus.objects.create(title="Test Corpus", creator=self.user)

        # Create test label
        self.label = AnnotationLabel.objects.create(
            text="Test Label", creator=self.user
        )

        # Create annotations on different pages
        # Page 1: 2 annotations
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Page 1 - Annotation 1",
            creator=self.user,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Page 1 - Annotation 2",
            creator=self.user,
            structural=True,
            bounding_box={"x": 10, "y": 10, "width": 10, "height": 10},
        )

        # Page 2: 3 annotations
        for i in range(3):
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=2,
                annotation_label=self.label,
                raw_text=f"Page 2 - Annotation {i+1}",
                creator=self.user,
                structural=False,
                bounding_box={"x": i * 10, "y": i * 10, "width": 10, "height": 10},
            )

        # Page 3: 1 annotation
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=3,
            annotation_label=self.label,
            raw_text="Page 3 - Annotation 1",
            creator=self.user,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        # Initialize GraphQL client
        self.client = Client(schema)
        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_single_page_backwards_compatibility(self):
        """Test that single page parameter still works."""
        query = """
        query ($docId: String!, $corpusId: ID!, $page: Int!) {
          document(id: $docId) {
            pageAnnotations(corpusId: $corpusId, page: $page) {
              id
              page
              rawText
            }
          }
        }
        """

        result = self.client.execute(
            query,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid, "page": 2},
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        annotations = result["data"]["document"]["pageAnnotations"]
        self.assertEqual(len(annotations), 3)  # 3 annotations on page 2
        for ann in annotations:
            self.assertEqual(ann["page"], 2)

    def test_multiple_pages(self):
        """Test querying multiple pages at once."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]) {
          document(id: $docId) {
            pageAnnotations(corpusId: $corpusId, pages: $pages) {
              id
              page
              rawText
              structural
            }
          }
        }
        """

        # Query pages 1 and 3
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1, 3],
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        annotations = result["data"]["document"]["pageAnnotations"]
        self.assertEqual(len(annotations), 3)  # 2 on page 1, 1 on page 3

        # Check we only got pages 1 and 3
        pages = {ann["page"] for ann in annotations}
        self.assertEqual(pages, {1, 3})

    def test_all_pages(self):
        """Test querying all pages."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]) {
          document(id: $docId) {
            pageAnnotations(corpusId: $corpusId, pages: $pages) {
              id
              page
            }
          }
        }
        """

        # Query all 3 pages
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1, 2, 3],
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        annotations = result["data"]["document"]["pageAnnotations"]
        self.assertEqual(len(annotations), 6)  # Total annotations across all pages

    def test_empty_pages_list(self):
        """Test that empty pages list returns empty results."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]) {
          document(id: $docId) {
            pageAnnotations(corpusId: $corpusId, pages: $pages) {
              id
            }
          }
        }
        """

        result = self.client.execute(
            query,
            variables={"docId": self.doc_gid, "corpusId": self.corpus_gid, "pages": []},
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        self.assertEqual(result["data"]["document"]["pageAnnotations"], [])

    def test_structural_filter_with_multiple_pages(self):
        """Test that structural filter works with multiple pages."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!], $structural: Boolean) {
          document(id: $docId) {
            pageAnnotations(corpusId: $corpusId, pages: $pages, structural: $structural) {
              id
              page
              structural
            }
          }
        }
        """

        # Get only structural annotations from pages 1 and 2
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1, 2],
                "structural": True,
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        annotations = result["data"]["document"]["pageAnnotations"]
        self.assertEqual(len(annotations), 1)  # Only 1 structural annotation on page 1
        self.assertTrue(all(ann["structural"] for ann in annotations))
