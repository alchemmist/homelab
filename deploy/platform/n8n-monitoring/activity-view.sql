-- Run on the n8n database only. No execution payloads, IDs or names are exposed.
BEGIN;
SET LOCAL lock_timeout = '2s';
SET LOCAL ROLE n8n;
CREATE VIEW public.socrat_execution_activity_v1 AS
WITH buckets(status) AS (VALUES ('success'), ('error'), ('other')),
counts AS (
  SELECT CASE WHEN status IN ('success','error') THEN status ELSE 'other' END AS bucket,
         count(*) AS starts
  FROM public.execution_entity
  WHERE "startedAt" BETWEEN now() - interval '5 minutes' AND now()
    AND status NOT IN ('running','waiting') AND "deletedAt" IS NULL
  GROUP BY 1
)
SELECT status, coalesce(starts,0)::bigint AS starts FROM buckets LEFT JOIN counts ON bucket=status;
GRANT CONNECT ON DATABASE n8n TO cnpg_metrics_exporter;
GRANT SELECT ON public.socrat_execution_activity_v1 TO cnpg_metrics_exporter;
COMMIT;
