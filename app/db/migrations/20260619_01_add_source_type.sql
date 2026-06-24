-- Add source_type column to opportunities table for distinguishing
-- post-level vs comment-level opportunities.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'opportunities' AND column_name = 'source_type'
    ) THEN
        ALTER TABLE opportunities ADD COLUMN source_type TEXT DEFAULT 'post';
    END IF;
END $$;
