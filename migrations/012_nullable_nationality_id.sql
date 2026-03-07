-- Migration 012: Make nationality_id and phone_number nullable in profile table
-- Users created via invitation don't have these fields yet.
-- Both columns had NOT NULL constraint which blocked invitation acceptance.

ALTER TABLE profile ALTER COLUMN nationality_id DROP NOT NULL;
ALTER TABLE profile ALTER COLUMN phone_number DROP NOT NULL;
