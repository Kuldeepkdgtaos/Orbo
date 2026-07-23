-- ============================================================
-- Reset OPERATIONAL data in the current database:
-- meetings, participants, transcripts, per-person + rollup summaries,
-- email deliveries, recurring templates, and cached aggregate summaries.
--
-- PRESERVES `users` and their per-user `dataentry_<email>` schemas, so logins
-- and Data Entry tables survive. Run this against prod BEFORE importing a
-- data-only backup so imported rows can't collide with existing ones.
--
-- Usage:
--   Local:  psql -U postgres -p 5433 -d standup -f db-truncate.sql
--   Neon:   psql "postgresql://<user>:<pw>@<host>/<db>?sslmode=require" -f db-truncate.sql
--
-- CASCADE clears dependent rows; RESTART IDENTITY resets the BIGSERIAL on
-- state_transitions. Safe to re-run.
-- ============================================================
TRUNCATE TABLE
    email_deliveries,
    standup_summaries,
    participant_summaries,
    aggregate_summaries,
    utterances,
    state_transitions,
    participants,
    standups,
    template_participants,
    standup_templates
RESTART IDENTITY CASCADE;

-- ------------------------------------------------------------
-- FULL reset (also removes accounts + their Data Entry data) — NOT run by
-- default. Uncomment only if you truly want to wipe users too. Note the
-- per-user `dataentry_<email>` schemas are created at runtime; drop them
-- separately if needed, e.g.:
--   DROP SCHEMA IF EXISTS "dataentry_<sanitized-email>" CASCADE;
--
-- TRUNCATE TABLE users RESTART IDENTITY CASCADE;
-- ------------------------------------------------------------
