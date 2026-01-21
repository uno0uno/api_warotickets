-- =============================================================================
-- MIGRATION FIX: Complete the restructure
-- Date: 2026-01-20
-- =============================================================================

BEGIN;

-- Drop empty old tables that conflict with new names
DROP TABLE IF EXISTS sale_stages CASCADE;
DROP TABLE IF EXISTS promotions CASCADE;

-- Rename new tables to final names
ALTER TABLE IF EXISTS sale_stages_new RENAME TO sale_stages;
ALTER TABLE IF EXISTS promotions_new RENAME TO promotions;

-- Update index names
ALTER INDEX IF EXISTS idx_sale_stages_new_cluster RENAME TO idx_sale_stages_cluster;
ALTER INDEX IF EXISTS idx_sale_stages_new_active RENAME TO idx_sale_stages_active;
ALTER INDEX IF EXISTS idx_promotions_new_cluster RENAME TO idx_promotions_cluster;
ALTER INDEX IF EXISTS idx_promotions_new_code RENAME TO idx_promotions_code;
ALTER INDEX IF EXISTS idx_promotions_new_active RENAME TO idx_promotions_active;

COMMIT;
