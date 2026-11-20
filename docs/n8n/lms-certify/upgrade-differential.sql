BEGIN;
ALTER TABLE lms_certification.pilot DROP CONSTRAINT IF EXISTS pilot_phase_check;
ALTER TABLE lms_certification.pilot ADD CONSTRAINT pilot_phase_check CHECK (phase IN ('solve','tests','public','repair','suite','mutate','expand','witness','audit','probes','wpublic','wsuite','plausible','certified','needs_review'));
COMMIT;
CREATE TABLE IF NOT EXISTS lms_certification.heartbeat (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), at timestamptz NOT NULL,
 execution_id text NOT NULL, decision text NOT NULL, ticks bigint NOT NULL
);
REVOKE ALL ON lms_certification.heartbeat FROM PUBLIC;
