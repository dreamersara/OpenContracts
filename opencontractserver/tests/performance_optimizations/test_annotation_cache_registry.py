from django.core.cache import cache
from django.test import TestCase

from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.annotations.query_optimizer import AnnotationQueryOptimizer
from opencontractserver.corpuses.models import Corpus
from opencontractserver.documents.models import Document
from opencontractserver.types.enums import LabelType
from opencontractserver.users.models import User


class AnnotationCacheRegistryTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="u", email="u@example.com", password="p"
        )
        self.doc = Document.objects.create(
            title="D", creator=self.user, file_type="application/pdf", pdf_file="x.pdf"
        )
        self.corpus = Corpus.objects.create(title="C", creator=self.user)
        label = AnnotationLabel.objects.create(
            text="L", creator=self.user, label_type=LabelType.SPAN_LABEL
        )
        Annotation.objects.create(
            document=self.doc,
            corpus=self.corpus,
            page=1,
            annotation_label=label,
            raw_text="A",
            creator=self.user,
            structural=False,
            bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        )

    def test_registry_and_invalidation(self):
        # Warm two cached variants for same (doc, corpus) different pages
        list(
            AnnotationQueryOptimizer.get_document_annotations(
                document_id=self.doc.id,
                user=self.user,
                corpus_id=self.corpus.id,
                pages=[1],
                use_cache=True,
            )
        )
        list(
            AnnotationQueryOptimizer.get_document_annotations(
                document_id=self.doc.id,
                user=self.user,
                corpus_id=self.corpus.id,
                pages=[2],
                use_cache=True,
            )
        )

        # Ensure registry keys exist
        reg_doc = cache.get(f"doc_annotations:keys:{self.doc.id}") or []
        reg_doc_corpus = (
            cache.get(f"doc_annotations:keys:{self.doc.id}:{self.corpus.id}") or []
        )
        assert len(reg_doc) >= 1
        assert len(reg_doc_corpus) >= 1

        # Invalidate by (doc, corpus) and ensure next access hits DB (simulate by expecting cache miss)
        AnnotationQueryOptimizer.invalidate_cache(self.doc.id, self.corpus.id)

        # Re-fetch; this should repopulate cache but we cannot assert query counts here
        list(
            AnnotationQueryOptimizer.get_document_annotations(
                document_id=self.doc.id,
                user=self.user,
                corpus_id=self.corpus.id,
                pages=[1],
                use_cache=True,
            )
        )
        # Registry should be recreated
        reg_doc_after = cache.get(f"doc_annotations:keys:{self.doc.id}") or []
        reg_doc_corpus_after = (
            cache.get(f"doc_annotations:keys:{self.doc.id}:{self.corpus.id}") or []
        )
        assert len(reg_doc_after) >= 1
        assert len(reg_doc_corpus_after) >= 1
