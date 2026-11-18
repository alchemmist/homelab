-- Run in a private database as schema owner. Grant the n8n credential role
-- USAGE on the schema and SELECT, UPDATE on the pilot table, nothing else.
CREATE SCHEMA IF NOT EXISTS lms_certification;
REVOKE ALL ON SCHEMA lms_certification FROM PUBLIC;
CREATE TABLE IF NOT EXISTS lms_certification.pilot (
    id text PRIMARY KEY,
    phase text NOT NULL CHECK (phase IN ('solve','tests','public','repair','suite','mutate','expand','certified','needs_review')),
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    owner text,
    lease_until timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON lms_certification.pilot FROM PUBLIC;
INSERT INTO lms_certification.pilot (id, phase) VALUES ('echo-0-v1', 'solve') ON CONFLICT DO NOTHING;
