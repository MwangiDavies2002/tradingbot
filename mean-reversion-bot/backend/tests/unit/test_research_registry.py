import hashlib
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.research_registry import router
from app.api.security import protect_api
from app.config import settings
from app.database.models import Base
from app.database.session import get_db
from app.institutional.registry import RunRequest, reserve_run
from app.institutional.data import fingerprint

ROOT = "/api/research-registry"
FAMILY = "a" * 32


def headers(role="operator"):
    return {"Authorization": f"Bearer {role * 32}"}


def run_body(trial="baseline", **changes):
    return dict(family_id=FAMILY, trial_key=trial, name="Option baseline", operation="option",
                dataset_version="synthetic-v1", payload={"kind": "call", "spot": 100,
                "strike": 100, "years": 1, "volatility": .2}) | changes


@pytest_asyncio.fixture
async def registry(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "registry.db").as_posix())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.middleware("http")(protect_api)
    app.include_router(router, prefix=ROOT)
    for role in ("admin", "operator", "viewer"):
        monkeypatch.setattr(settings, f"API_{role.upper()}_KEY_HASH", hashlib.sha256((role * 32).encode()).hexdigest())
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions
    await engine.dispose()


async def declare(client, keys=None):
    response = await client.post(ROOT + "/families", headers=headers(), json={
        "family_id": FAMILY, "name": "Synthetic study", "hypothesis": "Declared before results",
        "trial_keys": keys or ["baseline", "variant"]})
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_run_persistence_idempotency_export_and_family_completeness(registry):
    client, _ = registry
    await declare(client)
    response = await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "succeeded"
    repeated = await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    assert repeated.status_code == 200
    assert repeated.json() == result
    changed = await client.post(ROOT + "/runs", headers=headers(), json=run_body(dataset_version="changed"))
    assert changed.status_code == 409
    exported = await client.get(ROOT + f"/runs/{result['run_id']}/export", headers=headers("viewer"))
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    report = exported.json()["report"]
    assert report["result"]["price"] > 0
    assert fingerprint(report) == result["artifact_hash"]
    manifest = (await client.get(ROOT + f"/families/{FAMILY}", headers=headers())).json()
    assert manifest["unattempted_trial_keys"] == ["variant"]
    assert not manifest["all_trials_terminal"]


@pytest.mark.asyncio
async def test_failed_trials_are_retained_and_parent_lineage_is_checked(registry):
    client, _ = registry
    await declare(client)
    failed = await client.post(ROOT + "/runs", headers=headers(), json=run_body(payload={"spot": -1}))
    assert failed.status_code == 201
    assert failed.json()["status"] == "failed"
    parent = failed.json()["run_id"]
    success = await client.post(ROOT + "/runs", headers=headers(), json=run_body("variant", parent_run_id=parent))
    assert success.status_code == 201
    assert success.json()["parent_run_id"] == parent
    manifest = (await client.get(ROOT + f"/families/{FAMILY}", headers=headers())).json()
    assert manifest["all_trials_terminal"]
    listing = (await client.get(ROOT + "/runs?status=failed&operation=option", headers=headers())).json()
    assert [r["run_id"] for r in listing["runs"]] == [parent]


@pytest.mark.asyncio
async def test_option_portfolio_saved_report_retains_scenario_inputs(registry):
    client, _ = registry
    await declare(client)
    payload = json.loads((Path(__file__).resolve().parents[2] /
                          "examples/institutional/option-portfolio.json").read_text(encoding="utf-8"))
    response = await client.post(ROOT + "/runs", headers=headers(),
                                json=run_body(operation="option-portfolio", payload=payload))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "succeeded"
    exported = await client.get(ROOT + f"/runs/{result['run_id']}/export", headers=headers("viewer"))
    assert exported.status_code == 200
    report = exported.json()["report"]
    assert report["request"]["positions"][1]["contracts"] == -2
    assert report["result"]["scenarios"][0]["pnl"] == 0
    assert len(report["result"]["scenarios"]) == 2
    assert fingerprint(report) == result["artifact_hash"]


@pytest.mark.asyncio
async def test_pending_trial_is_not_rerun_and_only_admin_can_resolve(registry):
    client, sessions = registry
    await declare(client)
    async with sessions() as db:
        run, _ = await reserve_run(db, RunRequest(**run_body()), "operator")
        run_id = run.run_id
    retry = await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    assert retry.status_code == 202
    assert retry.json()["status"] == "pending"
    invalid_parent = await client.post(ROOT + "/runs", headers=headers(), json=run_body("variant", parent_run_id=run_id))
    assert invalid_parent.status_code == 409
    path = ROOT + f"/runs/{run_id}/resolve"
    body = {"evidence": "Worker interrupted during an isolated test; aborting this trial."}
    assert (await client.post(path, headers=headers(), json=body)).status_code == 403
    resolved = await client.post(path, headers=headers("admin"), json=body)
    assert resolved.json()["status"] == "aborted"
    assert (await client.post(path, headers=headers("admin"), json=body)).status_code == 409


@pytest.mark.asyncio
async def test_roles_validation_and_literal_search(registry):
    client, _ = registry
    assert (await client.get(ROOT + "/runs")).status_code == 401
    assert (await client.post(ROOT + "/families", headers=headers("viewer"), json={})).status_code == 403
    await declare(client)
    assert (await declare(client)).status_code == 200
    other = await client.post(ROOT + "/families", headers=headers(), json={
        "family_id": FAMILY, "name": "changed", "hypothesis": "changed", "trial_keys": ["other"]})
    assert other.status_code == 409
    assert (await client.post(ROOT + "/runs", headers=headers(), json=run_body("undeclared"))).status_code == 409
    assert (await client.post(ROOT + "/runs", headers=headers(), json=run_body(parent_run_id="b" * 32))).status_code == 409
    assert (await client.post(ROOT + "/runs", headers=headers(), content="x" * 2_000_001)).status_code == 413
    await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    assert len((await client.get(ROOT + "/runs?q=baseline&limit=1", headers=headers("viewer"))).json()["runs"]) == 1
    assert (await client.get(ROOT + "/runs?q=%25", headers=headers())).json()["runs"] == []
    assert (await client.get(ROOT + "/runs?limit=1000", headers=headers())).status_code == 422
    assert (await client.get(ROOT + "/runs/unknown/export", headers=headers())).status_code == 404


@pytest.mark.parametrize("table,column", [("research_families", "name"), ("research_runs", "name"), ("research_outcomes", "status")])
@pytest.mark.asyncio
async def test_database_rejects_updates_and_deletes(registry, table, column):
    client, sessions = registry
    await declare(client)
    await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    for sql in (f"UPDATE {table} SET {column} = 'changed'", f"DELETE FROM {table}"):
        async with sessions() as db:
            with pytest.raises(DatabaseError, match="append-only"):
                await db.execute(text(sql))
            await db.rollback()


@pytest.mark.asyncio
async def test_duplicate_concurrent_trial_has_one_run(registry):
    import asyncio
    client, _ = registry
    await declare(client)
    responses = await asyncio.gather(*[
        client.post(ROOT + "/runs", headers=headers(), json=run_body()) for _ in range(2)])
    assert all(r.status_code in (200, 201, 202) for r in responses)
    assert len({r.json()["run_id"] for r in responses}) == 1
    listing = (await client.get(ROOT + "/runs", headers=headers())).json()["runs"]
    assert len(listing) == 1
    assert listing[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_capacity_rejection_does_not_consume_trial(registry):
    from app.api.routes.institutional import _slots
    client, _ = registry
    await declare(client)
    assert _slots.acquire(blocking=False)
    assert _slots.acquire(blocking=False)
    try:
        response = await client.post(ROOT + "/runs", headers=headers(), json=run_body())
        assert response.status_code == 429
    finally:
        _slots.release()
        _slots.release()
    assert (await client.get(ROOT + "/runs", headers=headers())).json()["runs"] == []


@pytest.mark.parametrize("failure", [RuntimeError("Injected test failure"), ValueError()])
@pytest.mark.asyncio
async def test_unexpected_analysis_failure_is_durable(registry, monkeypatch, failure):
    client, _ = registry
    await declare(client)
    def fail(*args):
        raise failure
    monkeypatch.setattr("app.api.routes.research_registry.analyze", fail)
    response = await client.post(ROOT + "/runs", headers=headers(), json=run_body())
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "Injected" not in response.json()["error"]


@pytest.mark.parametrize("table,column", [("research_runs", "input_payload"), ("research_outcomes", "report")])
@pytest.mark.asyncio
async def test_export_detects_privileged_tampering(registry, table, column):
    client, sessions = registry
    await declare(client)
    created = (await client.post(ROOT + "/runs", headers=headers(), json=run_body())).json()
    async with sessions() as db:
        # Simulate a database administrator bypassing the guard, in this isolated fixture only.
        await db.execute(text(f"DROP TRIGGER {table}_no_update"))
        await db.execute(text(f"UPDATE {table} SET {column}='{{}}'"))
        await db.commit()
    response = await client.get(ROOT + f"/runs/{created['run_id']}/export", headers=headers())
    assert response.status_code == 409
    assert "integrity" in response.json()["detail"]
