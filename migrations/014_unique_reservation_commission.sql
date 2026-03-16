-- ============================================================================
-- Migration 014: UNIQUE constraint on order_commissions.reservation_id
-- Purpose: Enforce idempotency at DB level — prevent duplicate commissions
--          even under concurrent webhook retries or race conditions.
--
-- Why CONCURRENTLY: avoids ACCESS EXCLUSIVE lock on order_commissions
-- during index creation, so the table remains readable/writable in production.
--
-- IMPORTANT: CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
-- Run this file with psql directly:
--   psql $DATABASE_URL -f migrations/014_unique_reservation_commission.sql
-- Do NOT wrap in BEGIN/COMMIT.
-- ============================================================================

-- Step 1: Safety check — detect any existing duplicates before creating index.
-- If this query returns rows, resolve duplicates manually before proceeding.
--
-- SELECT reservation_id, COUNT(*) AS cnt
-- FROM order_commissions
-- GROUP BY reservation_id
-- HAVING COUNT(*) > 1;

-- Step 2: Create the unique index concurrently (no table lock).
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
    idx_order_commissions_unique_reservation
    ON order_commissions(reservation_id);

-- ============================================================================
-- Verification query (run after migration):
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'order_commissions'
--   AND indexname = 'idx_order_commissions_unique_reservation';
-- ============================================================================
