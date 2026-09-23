"""Append-only trial declarations and outcomes. No mutable status rows."""
import uuid
from typing import Annotated

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.models import ResearchFamily, ResearchRun, ResearchOutcome
from app.institutional.data import Record, fingerprint
from app.institutional.service import OPERATIONS, provenance

Identifier = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
TrialKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]


class FamilyRequest(Record):
    family_id: Identifier
    name: str = Field(min_length=1, max_length=128)
    hypothesis: str = Field(min_length=1, max_length=4000)
    trial_keys: list[TrialKey] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_trials(self):
        if len(set(self.trial_keys)) != len(self.trial_keys):
            raise ValueError("Trial keys must be unique and declared before running")
        return self


class RunRequest(Record):
    family_id: Identifier
    trial_key: TrialKey
    name: str = Field(min_length=1, max_length=128)
    operation: str = Field(min_length=1, max_length=64)
    dataset_version: str = Field(min_length=1, max_length=256)
    parent_run_id: Identifier | None = None
    payload: dict

    @model_validator(mode="after")
    def known_operation(self):
        if self.operation not in OPERATIONS:
            raise ValueError("Unknown analysis operation")
        fingerprint(self.payload)  # Reject non-finite or non-JSON values before persistence.
        return self


class RegistryConflict(ValueError):
    pass


async def declare_family(db, request: FamilyRequest, role: str):
    existing = await db.get(ResearchFamily, request.family_id)
    if existing is None:
        db.add(ResearchFamily(**request.model_dump(), created_by_role=role))
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
        existing = await db.get(ResearchFamily, request.family_id)
    if existing is None or any(getattr(existing, key) != value for key, value in request.model_dump().items()):
        raise RegistryConflict("Family ID already has a different immutable declaration")
    return existing


async def reserve_run(db, request: RunRequest, role: str):
    family = await db.get(ResearchFamily, request.family_id)
    if family is None or request.trial_key not in family.trial_keys:
        raise RegistryConflict("Declare the family and trial key before execution")
    if request.parent_run_id:
        if await db.get(ResearchOutcome, request.parent_run_id) is None:
            raise RegistryConflict("Parent run must exist and have a terminal outcome")
    request_hash = fingerprint(request.model_dump(mode="json"))
    query = select(ResearchRun).where(ResearchRun.family_id == request.family_id,
                                      ResearchRun.trial_key == request.trial_key)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise RegistryConflict("Trial key already used with different inputs; declare a new trial")
        return existing, False
    identity = provenance()
    run = ResearchRun(run_id=uuid.uuid4().hex, family_id=request.family_id, trial_key=request.trial_key,
                      name=request.name, operation=request.operation, dataset_version=request.dataset_version,
                      parent_run_id=request.parent_run_id, input_payload=request.payload,
                      request_hash=request_hash, created_by_role=role, **identity)
    db.add(run)
    try:
        await db.commit()  # Reservation survives cancellation/crash during analysis.
        return run, True
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(query)).scalar_one_or_none()
        if existing is None or existing.request_hash != request_hash:
            raise RegistryConflict("Concurrent request reserved this trial with different inputs")
        return existing, False


async def finish_run(db, run_id: str, role: str, *, report=None, error=None, aborted=False):
    outcome = await db.get(ResearchOutcome, run_id)
    if outcome is not None:
        return outcome
    if (report is None) == (error is None) or (aborted and error is None):
        raise ValueError("A terminal outcome requires either a report or a failure/abort reason")
    outcome = ResearchOutcome(run_id=run_id, status="aborted" if aborted else "failed" if error is not None else "succeeded",
        report=report, artifact_hash=fingerprint(report) if report is not None else None,
        error=error, completed_by_role=role)
    db.add(outcome)
    try:
        await db.commit()
        return outcome
    except IntegrityError:
        await db.rollback()
        existing = await db.get(ResearchOutcome, run_id)
        if existing is None:
            raise
        return existing


def run_summary(run, outcome):
    return {"run_id": run.run_id, "family_id": run.family_id, "trial_key": run.trial_key,
            "name": run.name, "operation": run.operation, "dataset_version": run.dataset_version,
            "parent_run_id": run.parent_run_id, "request_hash": run.request_hash,
            "implementation_hash": run.implementation_hash, "runtime": run.runtime,
            "created_at": run.created_at.isoformat() + "Z", "created_by_role": run.created_by_role,
            "status": outcome.status if outcome else "pending",
            "completed_at": outcome.completed_at.isoformat() + "Z" if outcome else None,
            "completed_by_role": outcome.completed_by_role if outcome else None,
            "artifact_hash": outcome.artifact_hash if outcome else None,
            "artifact_url": f"/api/research-registry/runs/{run.run_id}/export",
            "error": outcome.error if outcome else None}
