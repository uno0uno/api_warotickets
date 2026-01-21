-- =============================================================================
-- MIGRATION: Promotions Combo/Package System
-- Date: 2026-01-21
-- Description: Transform promotions from simple discounts to combo/package system
--              where promotions can include multiple areas with specific quantities
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. BACKUP EXISTING DATA
-- =============================================================================
CREATE TABLE promotions_backup_v1 AS SELECT * FROM promotions;
CREATE TABLE promotion_areas_backup_v1 AS SELECT * FROM promotion_areas;

-- =============================================================================
-- 2. CREATE NEW PROMOTION_ITEMS TABLE (replaces promotion_areas)
-- =============================================================================
CREATE TABLE promotion_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    promotion_id UUID NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    area_id INTEGER NOT NULL REFERENCES areas(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(promotion_id, area_id)
);

CREATE INDEX idx_promotion_items_promotion ON promotion_items(promotion_id);
CREATE INDEX idx_promotion_items_area ON promotion_items(area_id);

-- =============================================================================
-- 3. MIGRATE DATA FROM promotion_areas TO promotion_items
-- =============================================================================
INSERT INTO promotion_items (id, promotion_id, area_id, quantity, created_at)
SELECT id, promotion_id, area_id, 1, created_at
FROM promotion_areas;

-- =============================================================================
-- 4. MODIFY PROMOTIONS TABLE
-- =============================================================================

-- Add new pricing_type column (percentage, fixed_discount, fixed_price)
ALTER TABLE promotions ADD COLUMN pricing_type VARCHAR(20);

-- Migrate discount_type to pricing_type
UPDATE promotions
SET pricing_type = CASE
    WHEN discount_type = 'percentage' THEN 'percentage'
    WHEN discount_type = 'fixed' THEN 'fixed_discount'
    ELSE 'percentage'
END;

-- Make pricing_type NOT NULL with CHECK constraint
ALTER TABLE promotions ALTER COLUMN pricing_type SET NOT NULL;
ALTER TABLE promotions ADD CONSTRAINT chk_pricing_type
    CHECK (pricing_type IN ('percentage', 'fixed_discount', 'fixed_price'));

-- Rename discount_value to pricing_value
ALTER TABLE promotions RENAME COLUMN discount_value TO pricing_value;

-- Drop old discount_type column
ALTER TABLE promotions DROP COLUMN discount_type;

-- Drop min_quantity (now quantity is per area in promotion_items)
ALTER TABLE promotions DROP COLUMN min_quantity;

-- =============================================================================
-- 5. DROP OLD promotion_areas TABLE (data already backed up and migrated)
-- =============================================================================
DROP TABLE promotion_areas;

-- =============================================================================
-- 6. UPDATE promotion_code UNIQUE CONSTRAINT (make it unique per cluster)
-- =============================================================================
-- First drop the global unique constraint
ALTER TABLE promotions DROP CONSTRAINT IF EXISTS promotions_promotion_code_key;

-- Add composite unique constraint (code unique per cluster)
ALTER TABLE promotions ADD CONSTRAINT promotions_cluster_code_unique
    UNIQUE (cluster_id, promotion_code);

COMMIT;
