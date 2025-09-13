import logging

from celery import shared_task
from django.db import connection

logger = logging.getLogger(__name__)


@shared_task
def refresh_annotation_materialized_views(document_id=None, corpus_id=None):
    """
    Refresh materialized views for annotation data.
    Called after annotation create/update/delete.

    Args:
        document_id: Specific document to refresh (optional)
        corpus_id: Specific corpus to refresh (optional)
    """
    with connection.cursor() as cursor:
        try:
            # Refresh document summary
            if document_id and corpus_id:
                # Targeted refresh for specific document/corpus
                cursor.execute(
                    """
                    REFRESH MATERIALIZED VIEW CONCURRENTLY document_annotation_summary
                    WHERE document_id = %s AND corpus_id = %s
                """,
                    [document_id, corpus_id],
                )
            else:
                # Full refresh (expensive, use sparingly)
                cursor.execute(
                    """
                    REFRESH MATERIALIZED VIEW CONCURRENTLY document_annotation_summary
                """
                )

            logger.info(
                f"Refreshed document_annotation_summary for doc={document_id}, corpus={corpus_id}"
            )

        except Exception as e:
            logger.error(f"Failed to refresh materialized views: {e}")
            raise


@shared_task
def refresh_all_materialized_views():
    """
    Refresh all materialized views.
    Should be scheduled to run during low-traffic periods.
    """
    views = [
        "document_annotation_summary",
        "page_annotation_index",
        "label_usage_stats",
    ]

    with connection.cursor() as cursor:
        for view in views:
            try:
                cursor.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
                logger.info(f"Refreshed {view}")
            except Exception as e:
                logger.error(f"Failed to refresh {view}: {e}")
