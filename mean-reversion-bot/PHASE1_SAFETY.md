# Phase 1 Safety & Execution Architecture

> Verification note: see [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the current tested roadmap and remaining demo/deployment validation. This overview alone is not a production sign-off.

## Overview
Phase 1 implements the "Fail-Closed" safety architecture for the Mean Reversion Bot. It ensures that trading only occurs under strictly controlled conditions and that only one worker can operate a specific broker account at any given time.

## Key Components

### 1. Exclusive Worker Ownership (Advisory Locks)
- **Mechanism**: Uses PostgreSQL advisory locks (`pg_try_advisory_lock`) based on a hash of the `account_scope`.
- **File**: `backend/app/execution/safety.py` (`ExecutionStore.acquire`)
- **Safety**: Prevents multiple bot instances from trading on the same account, which could lead to double-execution or conflicting risk calculations.

### 2. Trading Control Gate
- **Database Table**: `trading_control`
- **Fields**:
  - `enabled`: Boolean master switch.
  - `heartbeat`: Updated after each safety loop (nominally every 2 seconds, plus broker/database processing time).
  - `recovery_error`: Captures reconciliation or startup errors that must be resolved before trading.
- **Requirement**: The `enabled` flag must be `true` AND `recovery_error` must be `null` for any order to be placed.

### 3. Execution Journaling
- **Database Table**: `execution_records`
- **Purpose**: Tracks every trade intent from "pending" to "closed".
- **Recovery**: On startup, the bot reconciles these records with the broker's active positions. If an order's state is uncertain, it halts and requires manual resolution via the `/api/bot/orders/{trade_id}/resolve` endpoint.

### 4. Circuit Breaker Integration
- **File**: `backend/app/core/risk/circuit_breaker.py`
- **Monitoring**:
  - Consecutive losses (Halt after 3)
  - Daily Drawdown (Pause at 5%)
  - Weekly Drawdown (Halt at 10%)
- **State Persistence**: The circuit breaker state is snapshotted into the `trading_control` table after every trade and heartbeat.

## Operational Workflow
1. **Startup**: Worker acquires Postgres lock.
2. **Reconciliation**: Worker checks `execution_records` vs Broker.
3. **Heartbeat**: Worker updates `heartbeat` and `risk_state` periodically.
4. **Emergency Stop**: Set `enabled = false` in `trading_control` to immediately block new entries via the `entry_gate`.
