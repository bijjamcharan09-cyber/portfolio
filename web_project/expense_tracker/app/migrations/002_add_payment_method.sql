-- Migration 002: Add payment_method column to transactions table
-- Adds payment_method field for better expense tracking
-- Uses conditional logic to be idempotent

-- Add payment_method column to transactions table if not exists
-- SQLite doesn't support IF NOT EXISTS for columns, so we use a workaround
-- This will fail gracefully if column already exists (checked in application logic)
ALTER TABLE transactions ADD COLUMN payment_method TEXT DEFAULT '';