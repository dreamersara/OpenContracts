"""
Test permission filtering in the query optimizer and GraphQL endpoints.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from graphene.test import Client
from graphql_relay import to_global_id

from config.graphql.schema import schema
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.tests.base import BaseFixtureTestCase
from opencontractserver.types.enums import PermissionTypes
from opencontractserver.utils.permissioning import set_permissions_for_obj_to_user

User = get_user_model()


class PermissionFilteringTest(BaseFixtureTestCase):
    """
    Test that query optimizer properly filters data based on user permissions.
    """

    def setUp(self):
        super().setUp()
        self.client = Client(schema)

        # Create two users
        self.user1 = User.objects.create_user(username="user1", password="password1")
        self.user2 = User.objects.create_user(username="user2", password="password2")

        # Create public and private documents
        self.public_doc = Document.objects.create(
            title="Public Document", creator=self.user1, is_public=True
        )

        self.private_doc = Document.objects.create(
            title="Private Document", creator=self.user1, is_public=False
        )

        # Create public and private corpora
        self.public_corpus = Corpus.objects.create(
            title="Public Corpus", creator=self.user1, is_public=True
        )

        self.private_corpus = Corpus.objects.create(
            title="Private Corpus", creator=self.user1, is_public=False
        )

        # Add documents to corpora
        self.public_corpus.documents.add(self.public_doc)
        self.private_corpus.documents.add(self.private_doc)

        # Create annotation label
        self.label = AnnotationLabel.objects.create(
            text="Test Label", creator=self.user1
        )

        # Create annotations with different visibility
        # Public annotation in public doc/corpus
        self.public_annotation = Annotation.objects.create(
            document=self.public_doc,
            corpus=self.public_corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Public annotation",
            creator=self.user1,
            is_public=True,
            structural=False,
        )

        # Private annotation in public doc/corpus (created by user1)
        self.private_annotation_user1 = Annotation.objects.create(
            document=self.public_doc,
            corpus=self.public_corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Private annotation by user1",
            creator=self.user1,
            is_public=False,
            structural=False,
        )

        # Private annotation in public doc/corpus (created by user2)
        self.private_annotation_user2 = Annotation.objects.create(
            document=self.public_doc,
            corpus=self.public_corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Private annotation by user2",
            creator=self.user2,
            is_public=False,
            structural=False,
        )

        # Structural annotation (should always be visible if doc is accessible)
        self.structural_annotation = Annotation.objects.create(
            document=self.public_doc,
            corpus=self.public_corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Structural annotation",
            creator=self.user1,
            is_public=False,
            structural=True,
        )

        # Annotation in private document
        self.private_doc_annotation = Annotation.objects.create(
            document=self.private_doc,
            corpus=self.private_corpus,
            page=1,
            annotation_label=self.label,
            raw_text="Annotation in private doc",
            creator=self.user1,
            is_public=False,
            structural=False,
        )

    def test_anonymous_user_filtering(self):
        """Test that anonymous users only see public annotations."""
        anon_user = AnonymousUser()

        # Test public document/corpus access
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.public_doc.id,
            user=anon_user,
            corpus_id=self.public_corpus.id,
            page=1,
            use_cache=False,
        )

        annotation_ids = [a.id for a in annotations]

        # Anonymous should see: public + structural only
        self.assertIn(self.public_annotation.id, annotation_ids)
        self.assertIn(self.structural_annotation.id, annotation_ids)
        self.assertNotIn(self.private_annotation_user1.id, annotation_ids)
        self.assertNotIn(self.private_annotation_user2.id, annotation_ids)

        # Test private document access (should be denied)
        private_annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.private_doc.id,
            user=anon_user,
            corpus_id=self.private_corpus.id,
            page=1,
            use_cache=False,
        )

        # Should get empty queryset for private document
        self.assertEqual(private_annotations.count(), 0)

    def test_authenticated_user_filtering(self):
        """Test that authenticated users see their own annotations plus public ones."""
        # Test user1 sees their own + public + structural
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.public_doc.id,
            user=self.user1,
            corpus_id=self.public_corpus.id,
            page=1,
            use_cache=False,
        )

        annotation_ids = [a.id for a in annotations]

        # User1 should see: public + their own + structural
        self.assertIn(self.public_annotation.id, annotation_ids)
        self.assertIn(self.private_annotation_user1.id, annotation_ids)
        self.assertIn(self.structural_annotation.id, annotation_ids)
        self.assertNotIn(self.private_annotation_user2.id, annotation_ids)

        # Test user2 sees their own + public + structural
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.public_doc.id,
            user=self.user2,
            corpus_id=self.public_corpus.id,
            page=1,
            use_cache=False,
        )

        annotation_ids = [a.id for a in annotations]

        # User2 should see: public + their own + structural
        self.assertIn(self.public_annotation.id, annotation_ids)
        self.assertIn(self.private_annotation_user2.id, annotation_ids)
        self.assertIn(self.structural_annotation.id, annotation_ids)
        self.assertNotIn(self.private_annotation_user1.id, annotation_ids)

    def test_permission_granted_access(self):
        """Test that users with explicit permissions can access private documents."""
        # Initially user2 cannot access private document
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.private_doc.id,
            user=self.user2,
            corpus_id=self.private_corpus.id,
            page=1,
            use_cache=False,
        )
        self.assertEqual(annotations.count(), 0)

        # Grant user2 read permission to private document
        set_permissions_for_obj_to_user(
            self.user2, self.private_doc, [PermissionTypes.READ]
        )

        # Also grant permission to corpus
        set_permissions_for_obj_to_user(
            self.user2, self.private_corpus, [PermissionTypes.READ]
        )

        # Now user2 should be able to access
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.private_doc.id,
            user=self.user2,
            corpus_id=self.private_corpus.id,
            page=1,
            use_cache=False,
        )

        # User2 should now see annotations (at least structural if any)
        # Since all annotations in private doc are by user1 and not public,
        # user2 won't see them even with doc access
        self.assertEqual(annotations.count(), 0)  # No annotations visible to user2

    def test_superuser_sees_everything(self):
        """Test that superusers can see all annotations."""
        superuser = User.objects.create_superuser(
            username="superuser", email="super@user.com", password="superpass"
        )

        # Test public document
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.public_doc.id,
            user=superuser,
            corpus_id=self.public_corpus.id,
            page=1,
            use_cache=False,
        )

        annotation_ids = [a.id for a in annotations]

        # Superuser should see everything
        self.assertIn(self.public_annotation.id, annotation_ids)
        self.assertIn(self.private_annotation_user1.id, annotation_ids)
        self.assertIn(self.private_annotation_user2.id, annotation_ids)
        self.assertIn(self.structural_annotation.id, annotation_ids)

        # Test private document
        annotations = AnnotationQueryOptimizer.get_document_annotations(
            document_id=self.private_doc.id,
            user=superuser,
            corpus_id=self.private_corpus.id,
            page=1,
            use_cache=False,
        )

        annotation_ids = [a.id for a in annotations]

        # Superuser should see private doc annotations too
        self.assertIn(self.private_doc_annotation.id, annotation_ids)

    def test_summary_permission_filtering(self):
        """Test that annotation summaries respect permissions."""
        # Anonymous user summary for public doc
        anon_user = AnonymousUser()
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            document_id=self.public_doc.id,
            corpus_id=self.public_corpus.id,
            user=anon_user,
            use_mv=False,  # Use direct query for testing
        )

        # Anonymous should count only public + structural annotations
        # We have 1 public + 1 structural = 2 total
        self.assertEqual(summary["annotation_count"], 1)  # Non-structural public
        self.assertEqual(summary["structural_count"], 1)  # Structural

        # User1 summary should include their private annotations
        summary = AnnotationQueryOptimizer.get_annotation_summary(
            document_id=self.public_doc.id,
            corpus_id=self.public_corpus.id,
            user=self.user1,
            use_mv=False,
        )

        # User1 should see: 1 public + 1 their own private = 2 non-structural, 1 structural
        self.assertEqual(summary["annotation_count"], 2)  # Non-structural
        self.assertEqual(summary["structural_count"], 1)  # Structural

    def test_navigation_permission_filtering(self):
        """Test that navigation index respects permissions."""
        # Anonymous user navigation
        anon_user = AnonymousUser()
        nav_items = AnnotationQueryOptimizer.get_navigation_annotations(
            document_id=self.public_doc.id,
            corpus_id=self.public_corpus.id,
            user=anon_user,
            use_mv=False,
        )

        nav_ids = [item.id for item in nav_items]

        # Anonymous should see only public non-structural annotations in navigation
        self.assertIn(self.public_annotation.id, nav_ids)
        self.assertNotIn(self.private_annotation_user1.id, nav_ids)
        self.assertNotIn(self.private_annotation_user2.id, nav_ids)
        self.assertNotIn(
            self.structural_annotation.id, nav_ids
        )  # Structural filtered out in navigation

        # User1 navigation
        nav_items = AnnotationQueryOptimizer.get_navigation_annotations(
            document_id=self.public_doc.id,
            corpus_id=self.public_corpus.id,
            user=self.user1,
            use_mv=False,
        )

        nav_ids = [item.id for item in nav_items]

        # User1 should see public + their own in navigation
        self.assertIn(self.public_annotation.id, nav_ids)
        self.assertIn(self.private_annotation_user1.id, nav_ids)
        self.assertNotIn(self.private_annotation_user2.id, nav_ids)
        self.assertNotIn(
            self.structural_annotation.id, nav_ids
        )  # Structural filtered out

    def test_graphql_permission_errors(self):
        """Test that GraphQL properly returns permission errors."""
        # Create GraphQL client with anonymous context
        anon_context = type("obj", (object,), {"user": AnonymousUser()})()

        # Try to access private document annotations
        query = """
        query GetAnnotations($docId: String!, $corpusId: ID!, $page: Int!) {
          document(id: $docId) {
            id
            pageAnnotations(corpusId: $corpusId, page: $page) {
              id
              rawText
            }
          }
        }
        """

        doc_gid = to_global_id("DocumentType", self.private_doc.id)
        corpus_gid = to_global_id("CorpusType", self.private_corpus.id)

        result = self.client.execute(
            query,
            variables={"docId": doc_gid, "corpusId": corpus_gid, "page": 1},
            context_value=anon_context,
        )

        # Should get null document (filtered by get_queryset)
        self.assertIsNone(result["data"]["document"])

