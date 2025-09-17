"""
Test page-filtered relationships functionality.
"""

from django.test import TestCase
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import (
    Annotation,
    AnnotationLabel,
    Relationship,
    RelationshipLabel,
)
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.types.enums import LabelType
from opencontractserver.users.models import User


class PageRelationshipsTest(TestCase):
    """Test the new page-filtered relationships functionality."""

    def setUp(self):
        """Set up test data with relationships spanning different pages."""
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

        # Create annotation label
        self.ann_label = AnnotationLabel.objects.create(
            text="Test Annotation Label",
            creator=self.user,
            label_type=LabelType.SPAN_LABEL,
        )

        # Create relationship label
        self.rel_label = RelationshipLabel.objects.create(
            text="Test Relationship", creator=self.user
        )

        # Create annotations on different pages
        self.ann_page1_a = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.ann_label,
            raw_text="Page 1 - Annotation A",
            creator=self.user,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        self.ann_page1_b = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=self.ann_label,
            raw_text="Page 1 - Annotation B",
            creator=self.user,
            bounding_box={"x": 20, "y": 20, "width": 10, "height": 10},
        )

        self.ann_page2_a = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=2,
            annotation_label=self.ann_label,
            raw_text="Page 2 - Annotation A",
            creator=self.user,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        self.ann_page3_a = Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=3,
            annotation_label=self.ann_label,
            raw_text="Page 3 - Annotation A",
            creator=self.user,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

        # Create relationships:
        # 1. Within page 1 (page1_a -> page1_b)
        self.rel_within_page1 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user,
        )
        self.rel_within_page1.source_annotations.set([self.ann_page1_a])
        self.rel_within_page1.target_annotations.set([self.ann_page1_b])

        # 2. Across pages 1 and 2 (page1_a -> page2_a)
        self.rel_page1_to_page2 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user,
        )
        self.rel_page1_to_page2.source_annotations.set([self.ann_page1_a])
        self.rel_page1_to_page2.target_annotations.set([self.ann_page2_a])

        # 3. Across pages 2 and 3 (page2_a -> page3_a)
        self.rel_page2_to_page3 = Relationship.objects.create(
            document=self.doc,
            corpus=self.corpus,
            relationship_label=self.rel_label,
            creator=self.user,
        )
        self.rel_page2_to_page3.source_annotations.set([self.ann_page2_a])
        self.rel_page2_to_page3.target_annotations.set([self.ann_page3_a])

        # Initialize GraphQL client
        self.client = Client(schema)
        self.doc_gid = to_global_id("DocumentType", self.doc.id)
        self.corpus_gid = to_global_id("CorpusType", self.corpus.id)

    def test_relationships_on_single_page(self):
        """Test getting relationships that touch a single page."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) {
              id
              relationshipLabel {
                text
              }
              sourceAnnotations {
                edges {
                  node {
                    page
                    rawText
                  }
                }
              }
              targetAnnotations {
                edges {
                  node {
                    page
                    rawText
                  }
                }
              }
            }
          }
        }
        """

        # Query page 1 - should get relationships within page 1 AND page1->page2
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [1],
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        relationships = result["data"]["document"]["pageRelationships"]
        self.assertEqual(
            len(relationships), 2
        )  # rel_within_page1 and rel_page1_to_page2

    def test_relationships_on_multiple_pages(self):
        """Test getting relationships that touch multiple pages."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) {
              id
            }
          }
        }
        """

        # Query pages 1 and 3 - should get all relationships except page2->page3
        # Because page1 touches rel_within_page1 and rel_page1_to_page2
        # And page3 touches rel_page2_to_page3
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
        relationships = result["data"]["document"]["pageRelationships"]
        self.assertEqual(
            len(relationships), 3
        )  # All relationships touch either page 1 or 3

    def test_relationships_page_2_only(self):
        """Test that page 2 gets the correct relationships."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) {
              id
            }
          }
        }
        """

        # Query page 2 - should get rel_page1_to_page2 and rel_page2_to_page3
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [2],
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        relationships = result["data"]["document"]["pageRelationships"]
        self.assertEqual(
            len(relationships), 2
        )  # rel_page1_to_page2 and rel_page2_to_page3

    def test_empty_pages_returns_no_relationships(self):
        """Test that empty pages list returns no relationships."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) {
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
        relationships = result["data"]["document"]["pageRelationships"]
        self.assertEqual(len(relationships), 0)

    def test_nonexistent_page_returns_no_relationships(self):
        """Test that querying a page with no annotations returns no relationships."""
        query = """
        query ($docId: String!, $corpusId: ID!, $pages: [Int!]!) {
          document(id: $docId) {
            pageRelationships(corpusId: $corpusId, pages: $pages) {
              id
            }
          }
        }
        """

        # Query page 99 which has no annotations
        result = self.client.execute(
            query,
            variables={
                "docId": self.doc_gid,
                "corpusId": self.corpus_gid,
                "pages": [99],
            },
            context_value=type("obj", (object,), {"user": self.user})(),
        )

        self.assertNotIn("errors", result)
        relationships = result["data"]["document"]["pageRelationships"]
        self.assertEqual(len(relationships), 0)
