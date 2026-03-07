-- Migration 012: Make nationality_id nullable in profile table
-- nationality_id is the user's national ID (cedula), not a foreign key.
-- Users created via invitation don't have this data yet.

ALTER TABLE profile ALTER COLUMN nationality_id DROP NOT NULL;
