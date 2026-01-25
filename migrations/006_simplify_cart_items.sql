-- Migration 006: Simplify cart_items - Store only user selection, calculate prices on read
-- This migration removes price columns from ticket_cart_items
-- Prices will be calculated in real-time when cart is loaded

-- Step 1: Drop the columns that store calculated values
ALTER TABLE ticket_cart_items
  DROP COLUMN IF EXISTS sale_stage_id,
  DROP COLUMN IF EXISTS tickets_count,
  DROP COLUMN IF EXISTS unit_price,
  DROP COLUMN IF EXISTS bundle_price,
  DROP COLUMN IF EXISTS original_price,
  DROP COLUMN IF EXISTS subtotal,
  DROP COLUMN IF EXISTS bundle_size;

-- Step 2: Update unique constraint to allow same area with different promotion_id
-- This enables: individual item for area + combo item for same area
ALTER TABLE ticket_cart_items DROP CONSTRAINT IF EXISTS ticket_cart_items_cart_id_area_id_key;

-- Create partial unique indexes instead of constraints (PostgreSQL doesn't allow functions in UNIQUE)
-- Index 1: For individual items (no promotion) - one per cart+area
CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_items_individual_unique
  ON ticket_cart_items (cart_id, area_id)
  WHERE promotion_id IS NULL;

-- Index 2: For promotion items - one per cart+area+promotion
CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_items_promo_unique
  ON ticket_cart_items (cart_id, area_id, promotion_id)
  WHERE promotion_id IS NOT NULL;

-- Result schema:
-- ticket_cart_items:
--   id UUID PK
--   cart_id UUID FK -> ticket_carts(id)
--   area_id INTEGER FK -> areas(id)
--   quantity INTEGER (bundles selected by user)
--   promotion_id UUID FK -> promotions(id) NULLABLE
--   created_at TIMESTAMPTZ
--   updated_at TIMESTAMPTZ
