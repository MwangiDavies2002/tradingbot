import hashlib
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.instrument_catalog import router
from app.api.security import protect_api
from app.config import settings
from app.database.models import Base
from app.database.session import get_db
from app.institutional.instrument_planning import InstrumentPlanRequest, plan_instrument_order


def spec(**changes):
    return dict(instrument_id="TEST_GOLD", venue="TEST", venue_symbol="TG", revision="v1",
        source="synthetic fixture", product="linear_contract", underlying_unit="ounce", quote_currency="USD",
        contract_size="100", tick_size="0.05", quantity_step="0.01", min_quantity="0.01", max_quantity="10",
        min_notional="1", published_ms=50, valid_from_ms=100, valid_until_ms=1000,
        sessions=[dict(open_ms=100, close_ms=500), dict(open_ms=600, close_ms=1000)]) | changes


def inputs(**changes):
    return dict(side="buy", quantity="0.03", limit_price="2000.10", arrival_price="2000", fee_bps="2",
        as_of_ms=200, book=dict(venue="TEST", venue_symbol="TG", quote_currency="USD", event_ms=180, available_ms=190,
        bids=[dict(price="2000", quantity="0.02"), dict(price="1999.95", quantity="0.05")],
        asks=[dict(price="2000.05", quantity="0.01"), dict(price="2000.10", quantity="0.03")])) | changes


def test_plan_units_fees_and_conservation():
    result = plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs()))
    assert result["filled_native_quantity"] == "0.03"
    assert result["filled_underlying_quantity"] == "3"
    assert result["filled_reference_notional"] == "6000.25"
    assert result["fees_scenario"] == "1.20005"
    assert result["arrival_shortfall_scenario"] == "1.45005"
    assert result["unfilled_native_quantity"] == "0"
    assert result["live_authorized"] is False


def test_limit_partial_fill_and_sell_cost_sign():
    partial = plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs(limit_price="2000.05")))
    assert partial["filled_native_quantity"] == "0.01"
    assert partial["unfilled_native_quantity"] == "0.02"
    sell = plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs(side="sell", limit_price="1999.95", fee_bps="0")))
    assert sell["filled_reference_notional"] == "5999.95"
    assert sell["arrival_shortfall_scenario"] == "0.05"
    assert sum(Decimal(f["native_quantity"]) for f in sell["projected_fills"]) == Decimal("0.03")


@pytest.mark.parametrize("changes,match", [
    ({"quantity": "0.031"}, "quantity_on_step"), ({"quantity": "11"}, "quantity_within_bounds"),
    ({"limit_price": "2000.051"}, "price_on_tick"), ({"as_of_ms": 500}, "session_open"),
    ({"as_of_ms": 1000}, "metadata_effective"), ({"as_of_ms": 189}, "unavailable"),
    ({"as_of_ms": 200, "max_age_ms": 10}, "stale"),
])
def test_order_constraints_block_plan(changes, match):
    with pytest.raises(ValueError, match=match):
        plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs(**changes)))


@pytest.mark.parametrize("field,value", [("venue", "WRONG"), ("venue_symbol", "WRONG"), ("quote_currency", "EUR")])
def test_book_identity_must_match(field, value):
    data = inputs()
    data["book"][field] = value
    with pytest.raises(ValueError, match="identity"):
        plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **data))


@pytest.mark.parametrize("field,value", [("price", "2000.051"), ("quantity", "0.011")])
def test_off_grid_depth_is_rejected(field, value):
    data = inputs()
    data["book"]["asks"][0][field] = value
    with pytest.raises(ValueError, match="grid"):
        plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **data))


@pytest.mark.parametrize("changes,match", [({"published_ms": 300}, "metadata_published"),
                                        ({"min_notional": "10000"}, "minimum_notional")])
def test_unknown_revision_and_minimum_notional_block(changes, match):
    with pytest.raises(ValueError, match=match):
        plan_instrument_order(InstrumentPlanRequest(instrument=spec(**changes), **inputs()))


def test_prior_session_snapshot_cannot_be_reused_after_reopening():
    with pytest.raises(ValueError, match="same trading session"):
        plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs(as_of_ms=600)))


def test_unmarketable_order_preserves_full_residual():
    result = plan_instrument_order(InstrumentPlanRequest(instrument=spec(), **inputs(limit_price="2000")))
    assert result["projected_fills"] == []
    assert result["filled_native_quantity"] == "0"
    assert result["unfilled_native_quantity"] == "0.03"
    assert result["vwap"] is None
    assert result["fees_scenario"] == "0"


def auth(role="admin"):
    return {"Authorization": f"Bearer {role * 32}"}


@pytest_asyncio.fixture
async def catalog(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///" + (tmp_path / "catalog.db").as_posix())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.middleware("http")(protect_api)
    app.include_router(router, prefix="/api/instruments")
    for role in ("admin", "operator", "viewer"):
        monkeypatch.setattr(settings, f"API_{role.upper()}_KEY_HASH", hashlib.sha256((role * 32).encode()).hexdigest())
    async def database():
        async with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_permissions_idempotency_and_revision_conflict(catalog):
    client, _ = catalog
    path = "/api/instruments/revisions"
    assert (await client.post(path, json=spec())).status_code == 401
    for role in ("operator", "viewer"):
        assert (await client.post(path, json=spec(), headers=auth(role))).status_code == 403
    first = await client.post(path, json=spec(), headers=auth())
    assert first.status_code == 201
    repeated = await client.post(path, json=spec(), headers=auth())
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert (await client.post(path, json=spec(tick_size="0.1"), headers=auth())).status_code == 409
    assert (await client.post(path, json=spec(revision="v2", tick_size="0.1"), headers=auth())).status_code == 201
    assert len((await client.get(path + "?q=TEST&venue=TEST", headers=auth("viewer"))).json()["revisions"]) == 2


@pytest.mark.asyncio
async def test_catalog_plan_pins_exact_revision_and_exports_full_contract(catalog):
    client, _ = catalog
    created = (await client.post("/api/instruments/revisions", json=spec(), headers=auth())).json()
    key = created["spec_hash"]
    await client.post("/api/instruments/revisions", json=spec(revision="v2", published_ms=300), headers=auth())
    response = await client.post("/api/instruments/plans", json=inputs() | {"spec_hash": key}, headers=auth("operator"))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["report"]["request"]["instrument"]["revision"] == "v1"
    assert data["report"]["result"]["instrument_hash"] == key
    assert data["catalog_observed_by_decision"] is False
    assert (await client.get(f"/api/instruments/revisions/{key}", headers=auth("viewer"))).status_code == 200
    assert (await client.post("/api/instruments/plans", json=inputs() | {"spec_hash": key}, headers=auth("viewer"))).status_code == 403
    assert (await client.post("/api/instruments/plans", json=inputs() | {"spec_hash": "0" * 64}, headers=auth("operator"))).status_code == 404
    assert (await client.post("/api/instruments/plans", json=inputs(quantity="0.031") | {"spec_hash": key}, headers=auth("operator"))).status_code == 422


@pytest.mark.asyncio
async def test_catalog_immutable_and_corruption_detected(catalog):
    client, sessions = catalog
    key = (await client.post("/api/instruments/revisions", json=spec(), headers=auth())).json()["spec_hash"]
    for sql in ("UPDATE instrument_revisions SET revision='changed'", "DELETE FROM instrument_revisions"):
        async with sessions() as db:
            with pytest.raises(DatabaseError, match="append-only"):
                await db.execute(text(sql))
            await db.rollback()
    async with sessions() as db:
        await db.execute(text("DROP TRIGGER instrument_revisions_no_update"))
        await db.execute(text("UPDATE instrument_revisions SET spec='{}'"))
        await db.commit()
    assert (await client.get(f"/api/instruments/revisions/{key}", headers=auth())).status_code == 409


@pytest.mark.asyncio
async def test_catalog_body_limits_and_shared_analysis_capacity(catalog):
    from app.api.routes.institutional import MAX_BODY_BYTES, _slots
    client, _ = catalog
    path = "/api/instruments/revisions"
    assert (await client.post(path, content="{", headers=auth())).status_code == 422
    assert (await client.post(path, json=[], headers=auth())).status_code == 422
    assert (await client.post(path, content=" " * (MAX_BODY_BYTES + 1), headers=auth())).status_code == 413
    key = (await client.post(path, json=spec(), headers=auth())).json()["spec_hash"]
    with _slots, _slots:
        response = await client.post("/api/instruments/plans", json=inputs() | {"spec_hash": key}, headers=auth())
        assert response.status_code == 429
    assert (await client.post("/api/instruments/plans", json=inputs() | {"spec_hash": key}, headers=auth())).status_code == 200
