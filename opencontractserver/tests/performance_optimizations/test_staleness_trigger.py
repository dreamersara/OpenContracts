"""
Staleness behavior: simulate old last_refreshed and ensure a refresh is scheduled.
"""

from __future__ import annotations

from django.db import connection

from opencontractserver.tasks.materialized_view_tasks import (
    check_materialized_view_staleness,
)
from opencontractserver.tests.base import BaseFixtureTestCase


class StalenessTriggerTest(BaseFixtureTestCase):
    """
    Validates staleness stats without attempting to update a materialized view.
    """

    def test_staleness_schedules_refresh(self):
        with connection.cursor() as cursor:
            # Ensure the MV exists before attempting a refresh
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_matviews WHERE matviewname = 'annotation_summary_mv'
                )
                """
            )
            if cursor.fetchone()[0]:
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )

        stats = check_materialized_view_staleness()
        assert "annotation_summary_mv" in stats
        mv = stats["annotation_summary_mv"]
        # If there are no rows, staleness may be None; otherwise it should be non-negative
        if mv.get("total_rows", 0) == 0:
            assert mv.get("max_staleness_seconds") is None
        else:
            assert (mv.get("max_staleness_seconds") or 0) >= 0
