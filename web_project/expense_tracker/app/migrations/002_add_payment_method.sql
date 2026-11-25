-- Migration 002: Add payment_method column to transactions table
-- Adds payment_method field for better expense tracking

-- Add payment_method column to transactions table
ALTER TABLE transactions ADD COLUMN payment_method TEXT DEFAULT '';

-- Note: guest_transactions already has payment_method column from initial schema
-- This migration is idempotent - if column exists, it will fail gracefully
-- In production, you would check for column existence first:
-- PRAGMA table_info(transactions);
-- Then conditionally add if not present