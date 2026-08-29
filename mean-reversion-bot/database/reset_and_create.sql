-- Use this when the existing Supabase tables are empty or disposable.
-- It removes old table definitions, then creates the exact application schema.
-- WARNING: this deletes all data in these tables.

begin;

drop table if exists public.backtest_results cascade;
drop table if exists public.config cascade;
drop table if exists public.bot_events cascade;
drop table if exists public.equity_snapshots cascade;
drop table if exists public.liquidity_zones cascade;
drop table if exists public.candles cascade;
drop table if exists public.signals cascade;
drop table if exists public.trades cascade;

commit;

-- After the reset succeeds, run database/schema.sql in the same Supabase SQL Editor.
