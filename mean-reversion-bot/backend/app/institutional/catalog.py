"""Immutable instrument revision persistence and integrity validation."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.models import InstrumentRevision
from app.institutional.data import fingerprint
from app.institutional.instruments import InstrumentSpec


class CatalogConflict(ValueError):
    pass


def validated_spec(row) -> InstrumentSpec:
    spec = InstrumentSpec.model_validate(row.spec)
    if fingerprint(spec.model_dump(mode="json")) != row.spec_hash or any(
        getattr(spec, field) != getattr(row, field) for field in ("instrument_id", "venue", "venue_symbol", "revision")
    ):
        raise CatalogConflict("Stored instrument specification failed its integrity check")
    return spec


def revision_summary(row):
    return {"spec_hash": row.spec_hash, "instrument_id": row.instrument_id, "venue": row.venue,
            "venue_symbol": row.venue_symbol, "revision": row.revision,
            "registered_at": row.registered_at.isoformat() + "Z", "registered_by_role": row.registered_by_role}


async def register_spec(db, spec: InstrumentSpec, role: str):
    payload = spec.model_dump(mode="json")
    key = fingerprint(payload)
    query = select(InstrumentRevision).where(InstrumentRevision.venue == spec.venue,
        InstrumentRevision.venue_symbol == spec.venue_symbol, InstrumentRevision.revision == spec.revision)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is None:
        row = InstrumentRevision(spec_hash=key, instrument_id=spec.instrument_id, venue=spec.venue,
            venue_symbol=spec.venue_symbol, revision=spec.revision, spec=payload, registered_by_role=role)
        db.add(row)
        try:
            await db.commit()
            return row, True
        except IntegrityError:
            await db.rollback()
            existing = (await db.execute(query)).scalar_one_or_none()
    if existing is None or existing.spec_hash != key:
        raise CatalogConflict("This venue/symbol revision already exists with different content; publish a new revision")
    validated_spec(existing)
    return existing, False
