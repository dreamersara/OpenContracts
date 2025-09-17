"""
Celery tasks for managing materialized views.
"""

import logging

from celery import shared_task
from django.core.cache import cache
from django.db import connection

logger = logging.getLogger(__name__)


@shared_task
def refresh_annotation_summary_mv(document_id=None, corpus_id=None):
    """
    Refresh the annotation summary materialized view.
    Can refresh the entire view or just for specific document/corpus.

    Args:
        document_id: Optional document ID to refresh for
        corpus_id: Optional corpus ID to refresh for
    """
    try:
        with connection.cursor() as cursor:
            if document_id and corpus_id:
                # Targeted refresh (full MV refresh currently, but we will overwrite per-user caches)
                logger.info(
                    f"Refreshing annotation_summary_mv for doc {document_id}, corpus {corpus_id}"
                )
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )

                # Read fresh summary once from MV
                cursor.execute(
                    """
                    SELECT
                        annotation_count,
                        structural_count,
                        user_annotation_count,
                        analysis_count,
                        page_count,
                        pages_with_annotations,
                        first_annotated_page,
                        last_annotated_page
                    FROM annotation_summary_mv
                    WHERE document_id = %s AND corpus_id = %s
                    """,
                    [document_id, corpus_id],
                )
                row = cursor.fetchone()
                fresh_summary = None
                if row:
                    fresh_summary = {
                        "annotation_count": row[0] or 0,
                        "structural_count": row[1] or 0,
                        "user_annotation_count": row[2] or 0,
                        "analysis_count": row[3] or 0,
                        "page_count": row[4] or 0,
                        "pages_with_annotations": row[5] or [],
                        "first_page": row[6],
                        "last_page": row[7],
                        "source": "materialized_view",
                    }

                # Overwrite per-user cached summaries registered for this pair
                registry_key = f"annotation_summary:users:{document_id}:{corpus_id}"
                try:
                    registry = cache.get(registry_key) or []
                except Exception:
                    registry = []

                if fresh_summary and registry:
                    for user_id in registry:
                        user_cache_key = (
                            f"annotation_summary:{document_id}:{corpus_id}:{user_id}"
                        )
                        cache.set(user_cache_key, fresh_summary, 300)

                # Best-effort cleanup of any legacy keys (optional)
                try:
                    cache.delete_pattern(
                        f"annotation_summary:{document_id}:{corpus_id}:*"
                    )
                except AttributeError:
                    logger.debug("Cache backend doesn't support pattern deletion")
            else:
                # Full refresh
                logger.info("Performing full refresh of annotation_summary_mv")
                cursor.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_summary_mv"
                )

        # Clear any related caches (broad cleanup only for full refresh)
        if not (document_id and corpus_id):
            try:
                cache.delete_pattern("annotation_summary:*")
            except AttributeError:
                logger.debug("Cache backend doesn't support pattern deletion")

        logger.info("Successfully refreshed annotation_summary_mv")
        return True

    except Exception as e:
        logger.error(f"Error refreshing annotation_summary_mv: {str(e)}")
        raise


@shared_task
def refresh_annotation_navigation_mv(document_id=None, corpus_id=None):
    """
    Refresh the annotation navigation materialized view.

    Args:
        document_id: Optional document ID to refresh for
        corpus_id: Optional corpus ID to refresh for
    """
    try:
        with connection.cursor() as cursor:
            logger.info("Refreshing annotation_navigation_mv")
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY annotation_navigation_mv"
            )

        # Clear navigation caches
        if document_id and corpus_id:
            cache_key = f"annotation_nav:{document_id}:{corpus_id}"
            cache.delete(cache_key)
        else:
            try:
                cache.delete_pattern("annotation_nav:*")
            except AttributeError:
                # Cache backend doesn't support pattern deletion (e.g., LocMemCache)
                logger.debug("Cache backend doesn't support pattern deletion")

        logger.info("Successfully refreshed annotation_navigation_mv")
        return True

    except Exception as e:
        logger.error(f"Error refreshing annotation_navigation_mv: {str(e)}")
        raise


@shared_task
def refresh_relationship_summary_mv(document_id=None, corpus_id=None):
    """
    Refresh the relationship summary materialized view.

    Args:
        document_id: Optional document ID to refresh caches for (full MV refresh still occurs)
        corpus_id: Optional corpus ID to refresh caches for (full MV refresh still occurs)
    """
    try:
        with connection.cursor() as cursor:
            logger.info("Refreshing relationship_summary_mv")
            cursor.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY relationship_summary_mv"
            )

            fresh_summary = None
            if document_id and corpus_id:
                # Load the updated summary row to overwrite per-user caches
                cursor.execute(
                    """
                    SELECT
                        document_id,
                        corpus_id,
                        relationship_count,
                        label_types,
                        pages_with_relationships,
                        last_refreshed
                    FROM relationship_summary_mv
                    WHERE document_id = %s AND corpus_id = %s
                    """,
                    [document_id, corpus_id],
                )
                row = cursor.fetchone()
                if row:
                    fresh_summary = {
                        "document_id": row[0],
                        "corpus_id": row[1],
                        "relationship_count": row[2] or 0,
                        "label_types": row[3] or 0,
                        "pages_with_relationships": row[4] or [],
                        "last_refreshed": row[5],
                        "source": "materialized_view",
                    }

        # Overwrite per-user cached summaries for this (doc, corpus)
        if document_id and corpus_id and fresh_summary:
            registry_key = f"relationship_summary:users:{document_id}:{corpus_id}"
            try:
                registry = cache.get(registry_key) or []
            except Exception:
                registry = []

            if registry:
                for user_id in registry:
                    user_cache_key = (
                        f"relationship_summary:{document_id}:{corpus_id}:{user_id}"
                    )
                    cache.set(user_cache_key, fresh_summary, 300)

            # Best-effort cleanup of any legacy keys
            try:
                cache.delete_pattern(
                    f"relationship_summary:{document_id}:{corpus_id}:*"
                )
            except AttributeError:
                logger.debug("Cache backend doesn't support pattern deletion")

        # Full refresh path: broad cleanup
        if not (document_id and corpus_id):
            try:
                cache.delete_pattern("relationship_summary:*")
            except AttributeError:
                logger.debug("Cache backend doesn't support pattern deletion")

        logger.info("Successfully refreshed relationship_summary_mv")
        return True
    except Exception as e:
        logger.error(f"Error refreshing relationship_summary_mv: {str(e)}")
        raise


@shared_task
def refresh_all_materialized_views():
    """
    Refresh all materialized views in the correct order.
    Called by periodic task or after bulk operations.
    """
    logger.info("Starting refresh of all materialized views")

    views_refreshed = []
    errors = []

    # Refresh in dependency order
    views_to_refresh = [
        "annotation_summary_mv",
        "annotation_navigation_mv",
        "relationship_summary_mv",
    ]

    for view_name in views_to_refresh:
        try:
            with connection.cursor() as cursor:
                logger.info(f"Refreshing {view_name}")
                cursor.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view_name}")
                views_refreshed.append(view_name)
                logger.info(f"Successfully refreshed {view_name}")
        except Exception as e:
            error_msg = f"Error refreshing {view_name}: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

    # Clear all related caches
    try:
        cache.delete_pattern("annotation_summary:*")
        cache.delete_pattern("annotation_nav:*")
        cache.delete_pattern("relationship_summary:*")
    except AttributeError:
        # If cache backend doesn't support pattern deletion
        logger.warning("Cache backend doesn't support pattern deletion")

    result = {
        "views_refreshed": views_refreshed,
        "errors": errors,
        "success": len(errors) == 0,
    }

    if errors:
        logger.error(f"Materialized view refresh completed with errors: {errors}")
    else:
        logger.info(f"Successfully refreshed all materialized views: {views_refreshed}")

    return result


@shared_task
def check_materialized_view_staleness():
    """
    Check how stale materialized views are and refresh if needed.
    Returns statistics about view staleness.
    """
    stats = {}

    try:
        with connection.cursor() as cursor:
            # Check annotation_summary_mv staleness
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_rows,
                    MIN(last_refreshed) as oldest_refresh,
                    MAX(last_refreshed) as newest_refresh,
                    EXTRACT(EPOCH FROM (NOW() - MIN(last_refreshed))) as max_staleness_seconds
                FROM annotation_summary_mv
            """
            )

            result = cursor.fetchone()
            if result:
                stats["annotation_summary_mv"] = {
                    "total_rows": result[0],
                    "oldest_refresh": result[1].isoformat() if result[1] else None,
                    "newest_refresh": result[2].isoformat() if result[2] else None,
                    "max_staleness_seconds": result[3],
                }

                # If any data is more than 5 minutes old, refresh
                if result[3] and result[3] > 300:
                    logger.info(
                        f"annotation_summary_mv is stale ({result[3]}s), triggering refresh"
                    )
                    refresh_annotation_summary_mv.delay()

            # Check relationship_summary_mv staleness
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_rows,
                    MIN(last_refreshed) as oldest_refresh,
                    MAX(last_refreshed) as newest_refresh,
                    EXTRACT(EPOCH FROM (NOW() - MIN(last_refreshed))) as max_staleness_seconds
                FROM relationship_summary_mv
            """
            )

            result_rel = cursor.fetchone()
            if result_rel:
                stats["relationship_summary_mv"] = {
                    "total_rows": result_rel[0],
                    "oldest_refresh": (
                        result_rel[1].isoformat() if result_rel[1] else None
                    ),
                    "newest_refresh": (
                        result_rel[2].isoformat() if result_rel[2] else None
                    ),
                    "max_staleness_seconds": result_rel[3],
                }

                # If any data is more than 5 minutes old, refresh
                if result_rel[3] and result_rel[3] > 300:
                    logger.info(
                        f"relationship_summary_mv is stale ({result_rel[3]}s), triggering refresh"
                    )
                    refresh_relationship_summary_mv.delay()

            # Check if views exist and have data
            cursor.execute(
                """
                SELECT
                    matviewname,
                    pg_size_pretty(pg_total_relation_size(matviewname::regclass)) as size
                FROM pg_matviews
                WHERE matviewname IN ('annotation_summary_mv', 'annotation_navigation_mv', 'relationship_summary_mv')
            """
            )

            for row in cursor.fetchall():
                view_name = row[0]
                if view_name not in stats:
                    stats[view_name] = {}
                stats[view_name]["size"] = row[1]

    except Exception as e:
        logger.error(f"Error checking materialized view staleness: {str(e)}")
        stats["error"] = str(e)

    return stats
