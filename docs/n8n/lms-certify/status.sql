-- No generated code, credentials, input/output or prompts in this report.
SELECT phase,coalesce(data->>'certificateScope',data->>'contract','legacy') AS scope,
       count(*),max(updated_at) AS last_checkpoint
FROM lms_certification.pilot WHERE id NOT LIKE 'validation/%' GROUP BY 1,2 ORDER BY 1,2;
SELECT id,phase,owner AS execution_id,lease_until,updated_at,
 data->>'calls' AS model_responses,jsonb_array_length(coalesce(data->'cases','[]')) AS cases,
 data->>'faultsKilled' AS killed,data->>'reviewReason' AS review_reason,data->>'lastPause' AS last_pause
FROM lms_certification.pilot WHERE phase NOT IN ('certified') AND data->>'contract'<>'draft_stdin'
ORDER BY updated_at DESC LIMIT 10;
SELECT at, execution_id, decision, ticks, now()-at AS last_tick_age FROM lms_certification.heartbeat;
