-- ============================================================================
-- Migration 015: Recalculate areas.service with flat fee formula
-- Purpose: Update all existing areas.service values to the new flat formula:
--          service = price * 3.26% + $1,894 COP
--
--          Replaces the old 4-tier capacity system:
--          - Tier 1-500:    price * 2.39% + $2,116
--          - Tier 501-2000: price * 2.39% + $1,894 (approx)
--          - etc.
--
-- Must run AFTER deploying commit f8eca3d (areas_service.py updated).
-- All new areas created after that commit already use the flat formula.
-- This migration fixes stale values for areas created before the deploy.
--
-- Run with:
--   psql $DATABASE_URL -f migrations/015_flat_service_fee.sql
-- ============================================================================

BEGIN;

UPDATE areas
SET
    service = CASE
        WHEN price <= 0 THEN 0
        ELSE ROUND((price * 0.0326 + 1894)::numeric, 0)
    END,
    updated_at = NOW()
WHERE status != 'disabled';

-- ============================================================================
-- Verification query (run after migration):
--
-- SELECT id, area_name, price, service,
--        ROUND((price * 0.0326 + 1894)::numeric, 0) AS expected
-- FROM areas
-- WHERE status != 'disabled'
-- ORDER BY id;
-- ============================================================================

COMMIT;
