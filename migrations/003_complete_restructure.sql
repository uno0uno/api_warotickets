-- =============================================================================
-- MIGRATION: Complete Restructure Sale Stages and Promotions
-- Date: 2026-01-20
-- =============================================================================

BEGIN;

-- =============================================================================
-- 1. DROP EMPTY CONFLICTING TABLES
-- =============================================================================
DROP TABLE IF EXISTS sale_stages CASCADE;
DROP TABLE IF EXISTS promotions CASCADE;

-- =============================================================================
-- 2. CREATE NEW SALE_STAGES TABLE (cluster level)
-- =============================================================================
CREATE TABLE sale_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    stage_name VARCHAR(100) NOT NULL,
    description TEXT,
    price_adjustment_type VARCHAR(20) NOT NULL CHECK (price_adjustment_type IN ('percentage', 'fixed')),
    price_adjustment_value NUMERIC NOT NULL,
    quantity_available INTEGER NOT NULL DEFAULT 0,
    quantity_sold INTEGER NOT NULL DEFAULT 0,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    priority_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sale_stages_cluster ON sale_stages(cluster_id);
CREATE INDEX idx_sale_stages_active ON sale_stages(cluster_id, is_active) WHERE is_active = true;

-- =============================================================================
-- 3. CREATE SALE_STAGE_AREAS LINK TABLE
-- =============================================================================
CREATE TABLE sale_stage_areas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sale_stage_id UUID NOT NULL REFERENCES sale_stages(id) ON DELETE CASCADE,
    area_id INTEGER NOT NULL REFERENCES areas(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(sale_stage_id, area_id)
);

CREATE INDEX idx_sale_stage_areas_stage ON sale_stage_areas(sale_stage_id);
CREATE INDEX idx_sale_stage_areas_area ON sale_stage_areas(area_id);

-- =============================================================================
-- 4. CREATE NEW PROMOTIONS TABLE (cluster level, code required)
-- =============================================================================
CREATE TABLE promotions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    promotion_name VARCHAR(100) NOT NULL,
    promotion_code VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    discount_type VARCHAR(20) NOT NULL CHECK (discount_type IN ('percentage', 'fixed')),
    discount_value NUMERIC NOT NULL,
    max_discount_amount NUMERIC,
    min_quantity INTEGER DEFAULT 1,
    quantity_available INTEGER,
    uses_count INTEGER NOT NULL DEFAULT 0,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    priority_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_promotions_cluster ON promotions(cluster_id);
CREATE INDEX idx_promotions_code ON promotions(promotion_code);
CREATE INDEX idx_promotions_active ON promotions(cluster_id, is_active) WHERE is_active = true;

-- =============================================================================
-- 5. CREATE PROMOTION_AREAS LINK TABLE
-- =============================================================================
CREATE TABLE promotion_areas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    promotion_id UUID NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    area_id INTEGER NOT NULL REFERENCES areas(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(promotion_id, area_id)
);

CREATE INDEX idx_promotion_areas_promotion ON promotion_areas(promotion_id);
CREATE INDEX idx_promotion_areas_area ON promotion_areas(area_id);

-- =============================================================================
-- 6. MIGRATE DATA FROM OLD TABLES
-- =============================================================================

-- Migrate area_sale_stages to sale_stages + sale_stage_areas
INSERT INTO sale_stages (
    id, cluster_id, stage_name, description, price_adjustment_type,
    price_adjustment_value, quantity_available, quantity_sold, start_time, end_time,
    is_active, priority_order, created_at, updated_at
)
SELECT
    ass.id,
    a.cluster_id,
    ass.stage_name,
    ass.description,
    ass.price_adjustment_type,
    ass.price_adjustment_value,
    ass.quantity_available::INTEGER,
    0 as quantity_sold,
    ass.start_time,
    ass.end_time,
    ass.is_active,
    ass.priority_order,
    ass.created_at,
    ass.updated_at
FROM area_sale_stages ass
JOIN areas a ON ass.area_id = a.id;

-- Create link entries for migrated sale stages
INSERT INTO sale_stage_areas (sale_stage_id, area_id)
SELECT ass.id, ass.area_id
FROM area_sale_stages ass;

-- Migrate area_promotions to promotions + promotion_areas
INSERT INTO promotions (
    id, cluster_id, promotion_name, promotion_code, description,
    discount_type, discount_value, max_discount_amount, min_quantity,
    quantity_available, uses_count, start_time, end_time,
    is_active, priority_order, created_at, updated_at
)
SELECT
    ap.id,
    a.cluster_id,
    ap.promotion_name,
    COALESCE(ap.promotion_code, 'MIGRATED_' || UPPER(SUBSTRING(ap.id::text, 1, 8))),
    ap.description,
    ap.discount_type,
    ap.discount_value,
    ap.max_discount_amount,
    COALESCE(ap.min_quantity, 1),
    ap.quantity_available,
    0 as uses_count,
    ap.start_time,
    ap.end_time,
    COALESCE(ap.is_active, true),
    COALESCE(ap.priority_order, 0),
    COALESCE(ap.created_at, NOW()),
    COALESCE(ap.updated_at, NOW())
FROM area_promotions ap
JOIN areas a ON ap.area_id = a.id;

-- Create link entries for migrated promotions
INSERT INTO promotion_areas (promotion_id, area_id)
SELECT ap.id, ap.area_id
FROM area_promotions ap;

-- =============================================================================
-- 7. RENAME OLD TABLES TO BACKUP
-- =============================================================================
ALTER TABLE area_sale_stages RENAME TO area_sale_stages_backup;
ALTER TABLE area_promotions RENAME TO area_promotions_backup;

COMMIT;
