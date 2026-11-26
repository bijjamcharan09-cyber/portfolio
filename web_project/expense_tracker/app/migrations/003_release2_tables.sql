-- Migration 003: Release 2 - Advanced Financial Management Tables
-- Creates tables for budgets, recurring transactions, financial goals, subscriptions, and notifications

-- Budgets table
CREATE TABLE IF NOT EXISTS budgets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    period          TEXT    NOT NULL CHECK (period IN ('weekly', 'monthly')),
    category        TEXT, -- NULL means overall budget across all categories
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    warning_threshold INTEGER NOT NULL DEFAULT 80 CHECK (warning_threshold BETWEEN 1 AND 100),
    start_date      TEXT    NOT NULL,
    end_date        TEXT, -- NULL means ongoing
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_budgets_user_id ON budgets(user_id);
CREATE INDEX IF NOT EXISTS idx_budgets_period ON budgets(period);
CREATE INDEX IF NOT EXISTS idx_budgets_category ON budgets(category);
CREATE INDEX IF NOT EXISTS idx_budgets_active ON budgets(user_id, is_active);

-- Recurring transactions table
CREATE TABLE IF NOT EXISTS recurring_transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT    NOT NULL CHECK (type IN ('income', 'expense')),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    category        TEXT    NOT NULL,
    note            TEXT    NOT NULL DEFAULT '',
    payment_method  TEXT    NOT NULL DEFAULT '',
    frequency       TEXT    NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    start_date      TEXT    NOT NULL,
    end_date        TEXT, -- NULL means no end date
    last_generated  TEXT, -- Last date a transaction was generated
    next_due_date   TEXT    NOT NULL, -- Next date a transaction should be generated
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    is_paused       INTEGER NOT NULL DEFAULT 0 CHECK (is_paused IN (0, 1)),
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recurring_user_id ON recurring_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_recurring_next_due ON recurring_transactions(next_due_date);
CREATE INDEX IF NOT EXISTS idx_recurring_active ON recurring_transactions(user_id, is_active, is_paused);
CREATE INDEX IF NOT EXISTS idx_recurring_frequency ON recurring_transactions(frequency);

-- Financial goals table
CREATE TABLE IF NOT EXISTS financial_goals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    target_amount_cents INTEGER NOT NULL CHECK (target_amount_cents > 0),
    current_amount_cents INTEGER NOT NULL DEFAULT 0 CHECK (current_amount_cents >= 0),
    target_date     TEXT, -- Optional deadline
    description     TEXT    NOT NULL DEFAULT '',
    is_completed    INTEGER NOT NULL DEFAULT 0 CHECK (is_completed IN (0, 1)),
    completed_at    TEXT, -- When goal was completed
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goals_user_id ON financial_goals(user_id);
CREATE INDEX IF NOT EXISTS idx_goals_completed ON financial_goals(user_id, is_completed);
CREATE INDEX IF NOT EXISTS idx_goals_target_date ON financial_goals(target_date);

-- Goal contributions table (tracks individual contributions to goals)
CREATE TABLE IF NOT EXISTS goal_contributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id         INTEGER NOT NULL REFERENCES financial_goals(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    note            TEXT    NOT NULL DEFAULT '',
    date            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contributions_goal_id ON goal_contributions(goal_id);
CREATE INDEX IF NOT EXISTS idx_contributions_user_id ON goal_contributions(user_id);
CREATE INDEX IF NOT EXISTS idx_contributions_date ON goal_contributions(date);

-- Subscriptions table
CREATE TABLE IF NOT EXISTS subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    currency        TEXT    NOT NULL DEFAULT 'INR',
    billing_cycle   TEXT    NOT NULL CHECK (billing_cycle IN ('monthly', 'quarterly', 'yearly', 'custom')),
    custom_cycle_days INTEGER, -- For custom billing cycles
    renewal_date    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
    category        TEXT    NOT NULL DEFAULT 'Subscription',
    payment_method  TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_renewal ON subscriptions(renewal_date);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_category ON subscriptions(category);

-- Notifications table
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT    NOT NULL, -- 'budget_warning', 'budget_exceeded', 'recurring_due', 'subscription_renewal', 'goal_milestone', 'goal_completed'
    title           TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    entity_type     TEXT, -- 'budget', 'recurring_transaction', 'subscription', 'goal'
    entity_id       TEXT, -- ID of the related entity
    is_read         INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    read_at         TEXT, -- When notification was read
    metadata_json   TEXT, -- Additional data as JSON
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type);
CREATE INDEX IF NOT EXISTS idx_notifications_entity ON notifications(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at);