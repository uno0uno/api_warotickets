-- Migration 005: Remove promotion_code requirement
-- The promotion_code field is no longer used in the new combo system

-- Make promotion_code nullable
ALTER TABLE promotions ALTER COLUMN promotion_code DROP NOT NULL;

-- Drop the unique constraint on promotion_code if it exists
ALTER TABLE promotions DROP CONSTRAINT IF EXISTS promotions_promotion_code_key;
ALTER TABLE promotions DROP CONSTRAINT IF EXISTS promotions_cluster_id_promotion_code_key;

-- Drop the index if exists
DROP INDEX IF EXISTS idx_promotions_code;
DROP INDEX IF EXISTS idx_promotions_new_code;
