"""
Add materialized view for relationship summaries.
Following patterns from migration 0037.
"""

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("annotations", "0038_add_relationship_performance_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            """
            -- Create materialized view for relationship summaries
            CREATE MATERIALIZED VIEW IF NOT EXISTS relationship_summary_mv AS
            WITH relationship_pages AS (
                -- Combine source and target annotation links once, then join to pages
                SELECT DISTINCT
                    ra.relationship_id,
                    ann.page
                FROM (
                    SELECT relationship_id, annotation_id
                    FROM annotations_relationship_source_annotations
                    UNION ALL
                    SELECT relationship_id, annotation_id
                    FROM annotations_relationship_target_annotations
                ) ra
                JOIN annotations_annotation ann
                  ON ann.id = ra.annotation_id
                WHERE ann.page IS NOT NULL
            )
            SELECT
                r.document_id,
                r.corpus_id,
                COUNT(DISTINCT r.id) as relationship_count,
                COUNT(DISTINCT r.relationship_label_id) as label_types,
                COALESCE(
                    array_agg(DISTINCT rp.page ORDER BY rp.page)
                    FILTER (WHERE rp.page IS NOT NULL),
                    '{}'::integer[]
                ) as pages_with_relationships,
                NOW() as last_refreshed
            FROM annotations_relationship r
            LEFT JOIN relationship_pages rp
              ON rp.relationship_id = r.id
            GROUP BY r.document_id, r.corpus_id;

            -- Create UNIQUE index to allow CONCURRENT refresh and fast lookups
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_summary_mv_doc_corpus
            ON relationship_summary_mv(document_id, corpus_id);
            """,
            reverse_sql="""
            DROP MATERIALIZED VIEW IF EXISTS relationship_summary_mv CASCADE;
            """
        ),
        migrations.RunSQL(
            """
            -- Create function to refresh relationship summary MV
            CREATE OR REPLACE FUNCTION refresh_relationship_summary_mv()
            RETURNS void AS $$
            BEGIN
                REFRESH MATERIALIZED VIEW CONCURRENTLY relationship_summary_mv;
            END;
            $$ LANGUAGE plpgsql;
            """,
            reverse_sql="DROP FUNCTION IF EXISTS refresh_relationship_summary_mv();"
        ),
    ]