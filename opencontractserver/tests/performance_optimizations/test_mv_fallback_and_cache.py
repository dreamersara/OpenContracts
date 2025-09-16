"""
Tests for MV fallback behavior and cache invalidation on refresh.
"""

from __future__ import annotations

from unittest.mock import patch

from opencontractserver.annotations import query_optimizer as qopt
from opencontractserver.annotations.models import Annotation, AnnotationLabel
from opencontractserver.corpuses.models import Corpus
from opencontractserver.tasks.materialized_view_tasks import (
    refresh_all_materialized_views,
)
from opencontractserver.tests.base import BaseFixtureTestCase


class MaterializedViewFallbackAndCacheTest(BaseFixtureTestCase):
    """
    Validates that MV-backed methods fall back cleanly when MV query fails,
    and that cache patterns are invalidated on full refresh.
    """

    def setUp(self):
        super().setUp()
        self.corpus = Corpus.objects.create(
            title="MV Fallback Corpus", creator=self.user
        )
        self.label = AnnotationLabel.objects.create(
            text="MV Fallback Label", creator=self.user
        )

        # Create 2 pages, 1 structural + 2 non-structural per page
        for page in [1, 2]:
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label,
                raw_text=f"S p{page}",
                creator=self.user,
                structural=True,
            )
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label,
                raw_text=f"NS1 p{page}",
                creator=self.user,
                structural=False,
            )
            Annotation.objects.create(
                document=self.doc,
                corpus=self.corpus,
                page=page,
                annotation_label=self.label,
                raw_text=f"NS2 p{page}",
                creator=self.user,
                structural=False,
            )

    def test_summary_fallback_when_mv_query_raises(self):
        """
        Using use_mv=True should fall through to direct query when MV query raises.
        """
        from django.db.backends.utils import CursorWrapper

        original_execute = CursorWrapper.execute

        def mock_execute(self, sql, params=None):
            # Only raise exception for MV queries, not for permission checks
            if isinstance(sql, str) and "annotation_summary_mv" in sql:
                raise Exception("MV error")
            # Call the original execute for other queries
            return original_execute(self, sql, params)

        with patch.object(CursorWrapper, "execute", mock_execute):
            summary = qopt.AnnotationQueryOptimizer.get_annotation_summary(
                self.doc.id, self.corpus.id, user=self.user, use_mv=True
            )

        assert summary["source"] == "direct_query"
        assert summary["annotation_count"] == 4  # two pages * 2 non-structural
        assert summary["structural_count"] == 2
        assert summary["page_count"] == 2
        assert summary["first_page"] == 1
        assert summary["last_page"] == 2

    def test_navigation_fallback_when_mv_query_raises(self):
        """
        Navigation should return a QuerySet (fallback) and correct items when MV query raises.
        """
        from django.db.backends.utils import CursorWrapper

        original_execute = CursorWrapper.execute

        def mock_execute(self, sql, params=None):
            # Only raise exception for MV queries, not for permission checks
            if isinstance(sql, str) and "annotation_navigation_mv" in sql:
                raise Exception("MV error")
            # Call the original execute for other queries
            return original_execute(self, sql, params)

        with patch.object(CursorWrapper, "execute", mock_execute):
            nav = qopt.AnnotationQueryOptimizer.get_navigation_annotations(
                self.doc.id, self.corpus.id, user=self.user, use_mv=True
            )

        # Fallback returns a QuerySet
        assert hasattr(nav, "query")
        assert len(list(nav)) == 4  # two pages * 2 non-structural

    def test_refresh_all_views_clears_cache_patterns(self):
        """
        Full refresh should attempt to clear summary and navigation cache patterns.
        """
        with patch(
            "opencontractserver.tasks.materialized_view_tasks.cache.delete_pattern",
            create=True,
        ) as mock_del:
            result = refresh_all_materialized_views()
            assert result["success"] is True
            # Called for both summary and nav patterns (order not guaranteed)
            calls = [c.args[0] for c in mock_del.call_args_list]
            assert "annotation_summary:*" in calls
            assert "annotation_nav:*" in calls

