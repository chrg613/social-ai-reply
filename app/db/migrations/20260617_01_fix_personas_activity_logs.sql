-- ============================================================================
-- Fix missing schema: is_active on personas_v1 + create activity_logs table
-- ============================================================================
-- Date:     2026-06-17
-- Author:   RedditFlow engineering
-- Concern:  personas_v1 table lacks is_active column used by the discovery
--           query layer. activity_logs table was referenced in code but never
--           created in this Supabase project.
-- Safety:   Idempotent (IF NOT EXISTS / DO blocks).
-- ============================================================================

-- 1. Add is_active column to personas_v1 if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'personas_v1' AND column_name = 'is_active'
    ) THEN
        ALTER TABLE personas_v1 ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
    END IF;
END $$;

-- 2. Create activity_logs table
CREATE TABLE IF NOT EXISTS activity_logs (
    id              SERIAL PRIMARY KEY,
    workspace_id    INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES account_users(id) ON DELETE SET NULL,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       TEXT,
    metadata_json   JSONB DEFAULT '{}',
    ip_address      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_logs_workspace_id ON activity_logs(workspace_id);
CREATE INDEX IF NOT EXISTS idx_activity_logs_created_at ON activity_logs(created_at DESC);

-- 3. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
