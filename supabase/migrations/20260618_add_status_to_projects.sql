-- ============================================================================
-- Add status column to projects table
-- ============================================================================
-- Date:     2026-06-18
-- Safety:   IF NOT EXISTS — idempotent.
-- ============================================================================

ALTER TABLE projects ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
UPDATE projects SET status = 'active' WHERE status IS NULL;
