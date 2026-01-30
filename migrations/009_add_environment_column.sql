-- ============================================================================
-- Migration 009: Add environment column to clusters table
-- Purpose: Enable filtering between dev/prod data in shared database
-- ============================================================================

-- Add environment column (default 'prod' for all existing events)
ALTER TABLE clusters
ADD COLUMN IF NOT EXISTS environment VARCHAR(10) DEFAULT 'prod';

-- Update any NULL values to 'prod'
UPDATE clusters SET environment = 'prod' WHERE environment IS NULL;

-- Add NOT NULL constraint after setting defaults
ALTER TABLE clusters
ALTER COLUMN environment SET NOT NULL;

-- Create index for environment filtering
CREATE INDEX IF NOT EXISTS idx_clusters_environment
ON clusters(environment);

-- Create composite index for public queries (is_active + shadowban + environment)
CREATE INDEX IF NOT EXISTS idx_clusters_public_env
ON clusters(is_active, shadowban, environment)
WHERE is_active = true AND shadowban = false;

-- Add check constraint to ensure only valid values
ALTER TABLE clusters
ADD CONSTRAINT chk_clusters_environment
CHECK (environment IN ('dev', 'prod'));

-- ============================================================================
-- Verification query (run after migration):
-- SELECT environment, COUNT(*) FROM clusters GROUP BY environment;
-- Expected: All existing events should be 'prod'
-- ============================================================================
