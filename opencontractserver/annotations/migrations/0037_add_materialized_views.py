from django.db import migrations


class Migration(migrations.Migration):
    """
    Materialized views for annotation aggregations.

    Index Strategy for Materialized Views:
    - UNIQUE indexes on materialized views (one summary per document+corpus)
    - UNIQUE index enables REFRESH MATERIALIZED VIEW CONCURRENTLY
    - Regular indexes for lookups

    Why Materialized Views?
    - Instant aggregation results (COUNT, MIN, MAX, etc.)
    - Avoid counting thousands of rows on every request
    - Trade-off: Slightly stale data (refresh on updates) for massive performance gain
    """

    dependencies = [
        ('annotations', '0036_add_performance_indexes'),
    ]

    operations = [
        # Summary view for instant stats
        migrations.RunSQL(
            """
            -- Materialized view for annotation statistics
            -- One row per document+corpus combination
            CREATE MATERIALIZED VIEW IF NOT EXISTS annotation_summary_mv AS
            SELECT
                document_id,
                corpus_id,
                COUNT(*) FILTER (WHERE structural = false)            AS annotation_count,
                COUNT(*) FILTER (WHERE structural = true)             AS structural_count,
                COUNT(*) FILTER (WHERE analysis_id IS NULL AND structural = false) AS user_annotation_count,
                COUNT(DISTINCT analysis_id) FILTER (WHERE analysis_id IS NOT NULL) AS analysis_count,
                COUNT(DISTINCT page)                                    AS page_count,
                array_agg(DISTINCT page ORDER BY page) FILTER (WHERE page IS NOT NULL) AS pages_with_annotations,
                MIN(page) AS first_annotated_page,
                MAX(page) AS last_annotated_page,
                NOW()     AS last_refreshed
            FROM annotations_annotation
            GROUP BY document_id, corpus_id;

            CREATE UNIQUE INDEX IF NOT EXISTS annotation_summary_mv_doc_corpus_uidx
            ON annotation_summary_mv(document_id, corpus_id);

            CREATE INDEX IF NOT EXISTS annotation_summary_mv_corpus_idx
            ON annotation_summary_mv(corpus_id);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS annotation_summary_mv CASCADE;"
        ),

        # Navigation index for jump-to functionality
        migrations.RunSQL(
            """
            -- Slim navigation MV for fast refresh
            CREATE MATERIALIZED VIEW IF NOT EXISTS annotation_navigation_mv AS
            SELECT
                a.id,
                a.document_id,
                a.corpus_id,
                a.page,
                a.bounding_box,
                a.analysis_id
            FROM annotations_annotation a
            WHERE a.structural = false;

            -- UNIQUE index required for CONCURRENT refresh
            CREATE UNIQUE INDEX IF NOT EXISTS annotation_navigation_mv_id_uidx
            ON annotation_navigation_mv(id);

            -- Helpful lookups
            CREATE INDEX IF NOT EXISTS annotation_navigation_mv_doc_corpus_idx
            ON annotation_navigation_mv(document_id, corpus_id);

            CREATE INDEX IF NOT EXISTS annotation_navigation_mv_corpus_analysis_idx
            ON annotation_navigation_mv(corpus_id, analysis_id);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS annotation_navigation_mv CASCADE;"
        ),
    ]