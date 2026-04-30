-- ============================================================
-- NexusOps — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- ── Waitlist table ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS waitlist (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    name        TEXT DEFAULT '',
    source      TEXT DEFAULT 'landing_page',
    ip_hash     TEXT DEFAULT '',          -- hashed IP, never raw
    created_at  TIMESTAMPTZ DEFAULT NOW(),

    -- Enforce unique emails at DB level (backend also handles gracefully)
    CONSTRAINT waitlist_email_unique UNIQUE (email),

    -- Validate email format at DB level too (defense in depth)
    CONSTRAINT waitlist_email_format CHECK (email ~* '^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'),

    -- Prevent absurdly long values
    CONSTRAINT waitlist_email_length CHECK (char_length(email) <= 254),
    CONSTRAINT waitlist_name_length  CHECK (char_length(name) <= 100)
);

-- ── Booking intents table ────────────────────────────────────
CREATE TABLE IF NOT EXISTS booking_intents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL,
    name        TEXT NOT NULL,
    message     TEXT DEFAULT '',
    ip_hash     TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT booking_email_format CHECK (email ~* '^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT booking_name_length  CHECK (char_length(name) <= 100),
    CONSTRAINT booking_msg_length   CHECK (char_length(message) <= 1000)
);

-- ── Indexes for query performance ───────────────────────────
CREATE INDEX IF NOT EXISTS idx_waitlist_email      ON waitlist (email);
CREATE INDEX IF NOT EXISTS idx_waitlist_created    ON waitlist (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_booking_email       ON booking_intents (email);
CREATE INDEX IF NOT EXISTS idx_booking_created     ON booking_intents (created_at DESC);

-- ── Row Level Security (RLS) ─────────────────────────────────
-- Lock down all direct client access. Only the service role key
-- (used by your backend) can read/write. Never expose this to the browser.
ALTER TABLE waitlist         ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_intents  ENABLE ROW LEVEL SECURITY;

-- Deny all access by default (service role bypasses RLS — that's correct)
-- No policies = no public access. Your FastAPI backend uses service role.
-- If you later want anon reads: add a SELECT policy explicitly.

-- ── Useful views (optional) ──────────────────────────────────
CREATE OR REPLACE VIEW waitlist_stats AS
SELECT
    COUNT(*)                                           AS total_signups,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS last_24h,
    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days')   AS last_7d,
    MIN(created_at)                                    AS first_signup,
    MAX(created_at)                                    AS latest_signup
FROM waitlist;
