"""Real PostgreSQL lock tests. CI supplies a disposable database explicitly."""
import asyncio
import os
import uuid
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database.models import Base
from app.execution.safety import ExecutionStore, control_row
from sqlalchemy.exc import DatabaseError

pytestmark = pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="Disposable PostgreSQL URL not configured")


@pytest.mark.asyncio
async def test_registry_concurrency_and_immutability(pg):
    from app.institutional.registry import FamilyRequest, RunRequest, declare_family, reserve_run, finish_run
    _, sessions = pg
    family_id = uuid.uuid4().hex
    async with sessions() as db:
        await declare_family(db, FamilyRequest(family_id=family_id, name="PG test", hypothesis="test", trial_keys=["a"]), "operator")
    request = RunRequest(family_id=family_id, trial_key="a", name="test", operation="option",
                         dataset_version="synthetic", payload={})
    async def reserve():
        async with sessions() as db:
            run, created = await reserve_run(db, request, "operator")
            return run.run_id, created
    results = await asyncio.gather(reserve(), reserve())
    assert len({r[0] for r in results}) == 1
    assert sum(r[1] for r in results) == 1
    async with sessions() as db:
        await finish_run(db, results[0][0], "operator", error="synthetic invalid input")
    for table, column in (("research_families", "name"), ("research_runs", "name"), ("research_outcomes", "status")):
        for statement in (f"UPDATE {table} SET {column}='changed'", f"DELETE FROM {table}"):
            async with sessions() as db:
                with pytest.raises(DatabaseError, match="append-only"):
                    await db.execute(text(statement))
                await db.rollback()


@pytest_asyncio.fixture
async def pg():
    schema = "test_safety_" + uuid.uuid4().hex
    admin = create_async_engine(os.environ["TEST_POSTGRES_URL"])
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["TEST_POSTGRES_URL"],
                                 connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, sessions
    await engine.dispose()
    async with admin.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin.dispose()


@pytest.mark.asyncio
async def test_exclusive_ownership_and_release(pg):
    engine, sessions = pg
    a = ExecutionStore(sessions, "deriv:demo:lock-test")
    b = ExecutionStore(sessions, a.scope)
    await a.acquire(engine)
    try:
        with pytest.raises(RuntimeError, match="Another worker"):
            await b.acquire(engine)
    finally:
        await a.release()
    await b.acquire(engine)
    await b.release()


@pytest.mark.asyncio
async def test_stop_serializes_with_admitted_entry(pg):
    engine, sessions = pg
    store = ExecutionStore(sessions, "deriv:demo:gate-test")
    await store.acquire(engine)
    async with sessions() as db:
        row = await control_row(db, store.scope)
        row.enabled = True; row.recovery_error = None
        await db.commit()
    async def stop():
        async with sessions() as db:
            row = await control_row(db, store.scope, lock=True)
            row.enabled = False
            await db.commit()
    try:
        async with store.entry_gate():
            task = asyncio.create_task(stop())
            await asyncio.sleep(.05)
            assert not task.done()
        await task
        with pytest.raises(RuntimeError, match="stopped"):
            async with store.entry_gate():
                pytest.fail("Entry passed a committed stop")
    finally:
        await store.release()
