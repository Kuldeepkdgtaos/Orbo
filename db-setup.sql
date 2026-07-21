-- ============================================================
-- AI Standup Manager — Database Setup Script
-- Matches shared/models.py exactly (A2A + MCP architecture, 2026-07-06).
--
-- Safe to run on a fresh database OR an existing one from an earlier
-- version of this app — every statement is idempotent (IF NOT EXISTS /
-- guarded ALTER), so re-running this script never touches existing data.
--
-- Usage (against your local Postgres on port 5433):
--   psql -U postgres -p 5433 -d standup -f db-setup.sql
--
-- (First time only, if the "standup" database doesn't exist yet:
--   psql -U postgres -p 5433 -c "CREATE DATABASE standup;")
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- TABLE: standup_templates
-- Persistent meeting configuration — configure once, run daily.
-- ============================================================
CREATE TABLE IF NOT EXISTS standup_templates (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT        NOT NULL,
    team_name             TEXT        NOT NULL,
    meeting_url           TEXT        NOT NULL,
    management_recipients JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TABLE: template_participants
-- Canonical participant definitions for a template.
-- Cloned into participants when a session is started.
-- ============================================================
CREATE TABLE IF NOT EXISTS template_participants (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id         UUID    NOT NULL REFERENCES standup_templates(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    email               TEXT    NOT NULL,
    teams_display_name  TEXT    NOT NULL,
    designation         TEXT,
    department          TEXT,
    order_index         INTEGER NOT NULL,
    is_manager          BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT uq_template_participants_order UNIQUE (template_id, order_index)
);

-- ============================================================
-- TABLE: standups
-- One row per standup occurrence (session or standalone).
-- template_id NULL  → standalone one-off standup.
-- template_id SET   → session spawned from a recurring template.
-- status lifecycle: idle → dispatched → in_progress → completed | failed
-- ============================================================
CREATE TABLE IF NOT EXISTS standups (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  TEXT        NOT NULL,
    team_name             TEXT        NOT NULL,
    meeting_url           TEXT        NOT NULL,
    status                VARCHAR(50) NOT NULL DEFAULT 'idle',
    scheduled_at          TIMESTAMPTZ,
    started_at            TIMESTAMPTZ,
    ended_at              TIMESTAMPTZ,
    recall_bot_id         TEXT,
    management_recipients JSONB       NOT NULL DEFAULT '[]'::jsonb,
    template_id           UUID        REFERENCES standup_templates(id) ON DELETE SET NULL,
    session_number        INTEGER,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_standups_template ON standups(template_id);

-- ============================================================
-- TABLE: participants
-- Participants in a specific standup session.
-- Cloned from template_participants when a session is started.
-- ============================================================
CREATE TABLE IF NOT EXISTS participants (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    standup_id          UUID    NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    email               TEXT    NOT NULL,
    teams_display_name  TEXT    NOT NULL,
    order_index         INTEGER NOT NULL,
    designation         TEXT,
    department          TEXT,
    is_manager          BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT uq_participants_standup_order UNIQUE (standup_id, order_index)
);

-- ============================================================
-- TABLE: state_transitions
-- Full audit trail of state machine steps. Drives SSE live status.
-- ============================================================
CREATE TABLE IF NOT EXISTS state_transitions (
    id          BIGSERIAL   PRIMARY KEY,
    standup_id  UUID        NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    from_state  TEXT,
    to_state    TEXT        NOT NULL,
    event       TEXT        NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_state_transitions_standup
    ON state_transitions (standup_id, occurred_at);

-- ============================================================
-- TABLE: utterances
-- Every attributed transcript line from the meeting.
-- participant_id is NULL when the speaker couldn't be attributed.
-- ============================================================
CREATE TABLE IF NOT EXISTS utterances (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    standup_id     UUID        NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    participant_id UUID        REFERENCES participants(id) ON DELETE SET NULL,
    speaker_label  TEXT        NOT NULL,
    text           TEXT        NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ NOT NULL,
    confidence     REAL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_utterances_standup
    ON utterances (standup_id, started_at);

-- ============================================================
-- TABLE: participant_summaries
-- GPT-4o generated summary per person per session (summarize_standup skill).
-- ============================================================
CREATE TABLE IF NOT EXISTS participant_summaries (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    standup_id     UUID        NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    participant_id UUID        NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    yesterday      TEXT        NOT NULL DEFAULT '',
    today          TEXT        NOT NULL DEFAULT '',
    blockers       TEXT        NOT NULL DEFAULT '',
    raw_response   JSONB,
    model          TEXT        NOT NULL,
    prompt_version TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_participant_summaries UNIQUE (standup_id, participant_id)
);

-- ============================================================
-- TABLE: standup_summaries
-- Executive rollup — one row per standup (summarize_standup skill).
-- ============================================================
CREATE TABLE IF NOT EXISTS standup_summaries (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    standup_id      UUID        NOT NULL UNIQUE REFERENCES standups(id) ON DELETE CASCADE,
    rollup_markdown TEXT        NOT NULL,
    key_blockers    JSONB       NOT NULL DEFAULT '[]'::jsonb,
    key_wins        JSONB       NOT NULL DEFAULT '[]'::jsonb,
    model           TEXT        NOT NULL,
    prompt_version  TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TABLE: email_deliveries
-- Audit of every email attempt via MS Graph (deliver_report skill).
-- status = 'sent' | 'failed'. A 'failed' row with a clear error is the
-- expected outcome while MS_GRAPH_* is left unconfigured.
-- ============================================================
CREATE TABLE IF NOT EXISTS email_deliveries (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    standup_id       UUID        NOT NULL REFERENCES standups(id) ON DELETE CASCADE,
    recipients       JSONB       NOT NULL,
    subject          TEXT        NOT NULL,
    body_preview     TEXT        NOT NULL,
    graph_message_id TEXT,
    status           VARCHAR(50) NOT NULL,
    error            TEXT,
    sent_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TABLE: users  (multi-user auth)
-- Only the per-user Data Entry schema is isolated by user; meetings,
-- standups, templates and summaries remain shared. This row gates access
-- (JWT auth) and owns a dedicated schema `dataentry_schema` (created at
-- registration time) holding the user's dynamic Data Entry tables.
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT        NOT NULL UNIQUE,
    password_hash    TEXT        NOT NULL,
    dataentry_schema TEXT        NOT NULL UNIQUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- TABLE: aggregate_summaries  (historic / cross-meeting rollups)
-- Cache of GPT-4o aggregated summaries over a date range + granularity.
-- Distinct from standup_summaries (one-per-standup); generated on-demand and
-- reused until a caller forces regeneration. subject_id is '' (not NULL) for
-- global/team scopes so the unique cache key dedups correctly.
-- ============================================================
CREATE TABLE IF NOT EXISTS aggregate_summaries (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    domain          TEXT        NOT NULL,                 -- standup | project
    scope           TEXT        NOT NULL,                 -- call | individual | project | overall
    granularity     TEXT        NOT NULL,                 -- overall | weekly | monthly
    range_start     DATE        NOT NULL,
    range_end       DATE        NOT NULL,
    subject_type    TEXT        NOT NULL DEFAULT 'global',-- global | team | participant | template
    subject_id      TEXT        NOT NULL DEFAULT '',
    bucket_key      TEXT        NOT NULL DEFAULT 'overall',
    rollup_markdown TEXT        NOT NULL,
    key_points      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    data_entry_refs JSONB       NOT NULL DEFAULT '[]'::jsonb,
    model           TEXT        NOT NULL,
    prompt_version  TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_aggregate_summaries_key
        UNIQUE (domain, scope, granularity, range_start, range_end, subject_id, bucket_key)
);

CREATE INDEX IF NOT EXISTS idx_aggregate_summaries_lookup
    ON aggregate_summaries (domain, scope, granularity, range_start, range_end);

-- ============================================================
-- UPGRADE GUARDS: add columns to pre-existing databases that predate them.
-- Safe to run on a fresh DB too — every guard is IF NOT EXISTS.
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='standups' AND column_name='template_id') THEN
        ALTER TABLE standups ADD COLUMN template_id UUID REFERENCES standup_templates(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='standups' AND column_name='session_number') THEN
        ALTER TABLE standups ADD COLUMN session_number INTEGER;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='participants' AND column_name='designation') THEN
        ALTER TABLE participants ADD COLUMN designation TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='participants' AND column_name='department') THEN
        ALTER TABLE participants ADD COLUMN department TEXT;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='participants' AND column_name='is_manager') THEN
        ALTER TABLE participants ADD COLUMN is_manager BOOLEAN NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='template_participants' AND column_name='is_manager') THEN
        ALTER TABLE template_participants ADD COLUMN is_manager BOOLEAN NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE tablename='standups' AND indexname='idx_standups_template') THEN
        CREATE INDEX idx_standups_template ON standups(template_id);
    END IF;

    -- domain discriminator (standup | project) on meetings + templates
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='standups' AND column_name='domain') THEN
        ALTER TABLE standups ADD COLUMN domain TEXT NOT NULL DEFAULT 'standup';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='standup_templates' AND column_name='domain') THEN
        ALTER TABLE standup_templates ADD COLUMN domain TEXT NOT NULL DEFAULT 'standup';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE tablename='standups' AND indexname='idx_standups_domain') THEN
        CREATE INDEX idx_standups_domain ON standups(domain);
    END IF;
END $$;

-- ============================================================
-- Verify: list all tables with row counts
-- ============================================================
SELECT
    t.table_name,
    COALESCE(s.n_live_tup, 0) AS row_count
FROM information_schema.tables t
LEFT JOIN pg_stat_user_tables s ON s.relname = t.table_name
WHERE t.table_schema = 'public'
ORDER BY t.table_name;
