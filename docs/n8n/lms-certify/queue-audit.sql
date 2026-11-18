-- Sanitized phase history: no solutions, tests or model payloads.
CREATE TABLE IF NOT EXISTS lms_certification.events (
 event_id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT clock_timestamp(),
 task_id text NOT NULL, execution_id text, phase text NOT NULL,
 calls integer NOT NULL, cases integer NOT NULL, faults_killed integer NOT NULL
);
REVOKE ALL ON lms_certification.events FROM PUBLIC;
CREATE OR REPLACE FUNCTION lms_certification.audit_checkpoint() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.phase IS DISTINCT FROM OLD.phase OR NEW.data IS DISTINCT FROM OLD.data THEN
 INSERT INTO lms_certification.events(task_id,execution_id,phase,calls,cases,faults_killed)
 VALUES (NEW.id,NEW.owner,NEW.phase,coalesce((NEW.data->>'calls')::int,0),
 jsonb_array_length(coalesce(NEW.data->'cases','[]'::jsonb)),coalesce((NEW.data->>'faultsKilled')::int,0));
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS audit_checkpoint ON lms_certification.pilot;
CREATE TRIGGER audit_checkpoint AFTER UPDATE ON lms_certification.pilot
FOR EACH ROW EXECUTE FUNCTION lms_certification.audit_checkpoint();
