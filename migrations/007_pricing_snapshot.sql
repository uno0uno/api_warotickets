-- Migration: Add pricing snapshot to reservation_units
-- Purpose: Store the price paid and discount context at time of purchase
-- so invoices reflect historical pricing, not current live data.
--
-- NOTE: a.service stores the per-unit service fee in COP (monetary amount),
-- NOT a percentage. The backfill uses a.service directly as service_fee.

-- Step 1: Add columns
ALTER TABLE reservation_units
  ADD COLUMN IF NOT EXISTS unit_price_paid numeric,
  ADD COLUMN IF NOT EXISTS pricing_snapshot jsonb;

-- Step 2: Backfill discounted reservation_units (with sale_stage or promotion)
-- Uses subquery to avoid PostgreSQL's UPDATE...FROM limitation with target table in JOINs.
UPDATE reservation_units ru SET
  unit_price_paid = sub.calc_price,
  pricing_snapshot = sub.calc_snapshot
FROM (
  SELECT
    ru2.id,
    CASE
      WHEN ss.price_adjustment_type = 'percentage'
        THEN a.price * (1 + ss.price_adjustment_value / 100)
      WHEN ss.price_adjustment_type = 'fixed'
        THEN (a.price * COALESCE(ssa.quantity, 1) + ss.price_adjustment_value) / COALESCE(ssa.quantity, 1)
      WHEN ss.price_adjustment_type = 'fixed_price'
        THEN ss.price_adjustment_value / COALESCE(ssa.quantity, 1)
      WHEN p.pricing_type = 'percentage'
        THEN a.price * (1 - p.pricing_value / 100)
      WHEN p.pricing_type = 'fixed_discount'
        THEN a.price - p.pricing_value
      WHEN p.pricing_type = 'fixed_price'
        THEN p.pricing_value
      ELSE a.price
    END AS calc_price,
    jsonb_build_object(
      'base_price', a.price,
      'unit_price', CASE
        WHEN ss.price_adjustment_type = 'percentage'
          THEN a.price * (1 + ss.price_adjustment_value / 100)
        WHEN ss.price_adjustment_type = 'fixed'
          THEN (a.price * COALESCE(ssa.quantity, 1) + ss.price_adjustment_value) / COALESCE(ssa.quantity, 1)
        WHEN ss.price_adjustment_type = 'fixed_price'
          THEN ss.price_adjustment_value / COALESCE(ssa.quantity, 1)
        WHEN p.pricing_type = 'percentage'
          THEN a.price * (1 - p.pricing_value / 100)
        WHEN p.pricing_type = 'fixed_discount'
          THEN a.price - p.pricing_value
        WHEN p.pricing_type = 'fixed_price'
          THEN p.pricing_value
        ELSE a.price
      END,
      'service_fee', COALESCE(a.service, 0),
      'discount_type', CASE
        WHEN ru2.applied_area_sale_stage_id IS NOT NULL THEN 'sale_stage'
        WHEN ru2.applied_promotion_id IS NOT NULL THEN 'promotion'
        ELSE null
      END,
      'discount_name', COALESCE(ss.stage_name, p.promotion_name),
      'promotion_code', p.promotion_code,
      'adjustment_type', COALESCE(ss.price_adjustment_type, p.pricing_type),
      'adjustment_value', COALESCE(ss.price_adjustment_value, p.pricing_value),
      'bundle_size', COALESCE(ssa.quantity, 1)
    ) AS calc_snapshot
  FROM reservation_units ru2
  JOIN units u ON ru2.unit_id = u.id
  JOIN areas a ON u.area_id = a.id
  LEFT JOIN sale_stages ss ON ru2.applied_area_sale_stage_id = ss.id
  LEFT JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id AND ssa.area_id = a.id
  LEFT JOIN promotions p ON ru2.applied_promotion_id = p.id
  WHERE (ru2.applied_area_sale_stage_id IS NOT NULL OR ru2.applied_promotion_id IS NOT NULL)
) sub
WHERE ru.id = sub.id;

-- Step 3: Backfill units with no discount (no sale_stage, no promotion)
UPDATE reservation_units ru SET
  unit_price_paid = a.price,
  pricing_snapshot = jsonb_build_object(
    'base_price', a.price,
    'unit_price', a.price,
    'service_fee', COALESCE(a.service, 0),
    'discount_type', null,
    'discount_name', null,
    'promotion_code', null,
    'adjustment_type', null,
    'adjustment_value', null,
    'bundle_size', 1
  )
FROM units u
JOIN areas a ON u.area_id = a.id
WHERE ru.unit_id = u.id
  AND ru.unit_price_paid IS NULL;
