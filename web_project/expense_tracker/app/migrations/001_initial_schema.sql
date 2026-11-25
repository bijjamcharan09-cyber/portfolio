-- Migration 001: Initial Schema
-- Creates the core tables for Expense Tracker application

-- Users table with RBAC support
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Transactions table (user-isolated)
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    type         TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    date         TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_transactions_user_date_type ON transactions(user_id, date, type);

-- Guest transactions (isolated temporary storage)
CREATE TABLE IF NOT EXISTS guest_transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guest_id       TEXT    NOT NULL,
    type           TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    category       TEXT    NOT NULL,
    note           TEXT    NOT NULL DEFAULT '',
    payment_method TEXT    NOT NULL DEFAULT '',
    date           TEXT    NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at     TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_guest_tx_guest ON guest_transactions(guest_id);
CREATE INDEX IF NOT EXISTS idx_guest_tx_expires ON guest_transactions(expires_at);

-- Audit log table
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER,
    action        TEXT    NOT NULL,
    entity_type   TEXT,
    entity_id     TEXT,
    timestamp     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    request_id    TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);

-- Migration tracking table
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    rolled_back INTEGER NOT NULL DEFAULT 0
);