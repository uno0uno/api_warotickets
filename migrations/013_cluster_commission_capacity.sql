-- ============================================================================
-- Migration 013: Add commission_percentage and total_capacity to clusters
-- Purpose: Store default cluster-level commission rate and denormalized capacity
-- Safe strategy: ADD only — no columns dropped in this migration
-- ============================================================================

-- Step 1: Add columns (idempotent)
ALTER TABLE clusters
  ADD COLUMN IF NOT EXISTS commission_percentage NUMERIC(5,2) NOT NULL DEFAULT 10.00,
  ADD COLUMN IF NOT EXISTS total_capacity INTEGER DEFAULT 0;

-- Step 2: Populate total_capacity from active areas
-- Matches the on-the-fly logic in public.py: sum(a.capacity for a in areas if status != 'disabled')
UPDATE clusters c
SET total_capacity = COALESCE(
  (SELECT SUM(a.capacity)
   FROM areas a
   WHERE a.cluster_id = c.id AND a.status != 'disabled'),
  0
);

-- Step 3: Populate commission_percentage from promoter_event_configs (if any active config exists)
-- Falls back to the column default (10.00) when no config exists for the cluster
UPDATE clusters c
SET commission_percentage = COALESCE(
  (SELECT ROUND(AVG(pec.commission_percentage)::numeric, 2)
   FROM promoter_event_configs pec
   WHERE pec.cluster_id = c.id AND pec.is_active = true),
  10.00
);

-- Step 4: Index for querying clusters by commission tier
CREATE INDEX IF NOT EXISTS idx_clusters_commission_pct ON clusters(commission_percentage);

-- ============================================================================
-- Columns NOT touched in this migration (per safe-migration strategy):
--   areas.service                            -> recalculated separately (Fase 3 del epic)
--   promoter_event_configs.commission_percentage -> remains as per-promoter override
--   promoter_codes.commission_percentage     -> remains as per-promoter fallback
--
-- Commission precedence hierarchy (to be enforced in commissions_service.py, future ticket):
--   1. promoter_event_configs.commission_percentage  (most specific: per promoter+cluster)
--   2. clusters.commission_percentage               (cluster default — added in this migration)
--   3. promoter_codes.commission_percentage         (least specific: per promoter)
-- ============================================================================

-- ============================================================================
-- Verification queries (run after migration to validate):
--
-- Confirm columns exist:
-- SELECT column_name, data_type, column_default, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'clusters'
--   AND column_name IN ('commission_percentage', 'total_capacity');
--
-- Spot-check migrated data:
-- SELECT id, commission_percentage, total_capacity FROM clusters LIMIT 10;
--
-- Verify total_capacity matches sum of active areas (expect 0 rows if correct):
-- SELECT c.id, c.total_capacity AS stored,
--        COALESCE(SUM(a.capacity) FILTER (WHERE a.status != 'disabled'), 0) AS calculated
-- FROM clusters c
-- LEFT JOIN areas a ON a.cluster_id = c.id
-- GROUP BY c.id, c.total_capacity
-- HAVING c.total_capacity != COALESCE(SUM(a.capacity) FILTER (WHERE a.status != 'disabled'), 0);
--
-- Confirm index created:
-- SELECT indexname FROM pg_indexes
-- WHERE tablename = 'clusters' AND indexname = 'idx_clusters_commission_pct';
-- ============================================================================
