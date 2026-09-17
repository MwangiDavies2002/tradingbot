-- Apply once before deploying the Phase 1 worker/API to an existing Postgres DB.
-- Additive tables; no existing trade history is deleted.
BEGIN;
CREATE TABLE IF NOT EXISTS trading_control (
    scope VARCHAR(96) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    reset_version INTEGER NOT NULL DEFAULT 0,
    reset_applied INTEGER NOT NULL DEFAULT 0,
    heartbeat TIMESTAMP,
    recovery_error TEXT,
    risk_state JSON NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS execution_records (
    trade_id VARCHAR(32) PRIMARY KEY,
    scope VARCHAR(96) NOT NULL,
    status VARCHAR(16) NOT NULL,
    payload JSON NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_execution_records_scope ON execution_records(scope);
ALTER TABLE trades ALTER COLUMN contract_id TYPE BIGINT;
COMMIT;
