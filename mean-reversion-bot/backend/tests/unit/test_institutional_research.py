from copy import deepcopy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.institutional import router
from app.api.security import protect_api
from app.config import settings
from app.institutional.research import ExperimentRequest, MultipleTestingRequest, adjust_tests, experiment
from app.institutional.service import analyze


def samples():
    return [dict(decision_ms=i*100, features_available_ms=i*100, target_available_ms=(i+2)*100,
                 features=[(i % 10) - 5], target_return=((i % 10)-5) * .001) for i in range(100)]


def test_expanding_training_purges_unknown_targets_and_future_changes():
    request = dict(name="synthetic-only", samples=samples(), feature_names=["test"], cost_bps=0)
    before = experiment(ExperimentRequest(**request))
    changed = deepcopy(request)
    for sample in changed["samples"][70:]:
        sample["features"] = [1000]
        sample["target_return"] = -.5
    after = experiment(ExperimentRequest(**changed))
    assert before["folds"][0] == after["folds"][0]
    for fold in before["folds"]:
        assert fold["training_last_target_ms"] < fold["test_start_ms"]
        assert fold["purged_samples"] == 2
        assert fold["mse"] < fold["training_mean_baseline_mse"]
    assert before["live_authorized"] is False


def test_feature_leakage_rejected():
    data = samples()
    data[0]["features_available_ms"] = 1
    with pytest.raises(ValueError, match="known at decision"):
        ExperimentRequest(name="bad", samples=data, feature_names=["test"])


def test_multiple_testing_known_values():
    result = adjust_tests(MultipleTestingRequest(p_values={"a": .01, "b": .04, "c": .03, "d": .2}))
    assert result["adjusted_p_values"] == pytest.approx({"a": .04, "b": .0533333333, "c": .0533333333, "d": .2})
    assert result["discoveries"] == ["a"]


def test_reports_reproducible_and_self_contained():
    payload = {"kind": "call", "spot": 100, "strike": 100, "years": 1, "volatility": .2}
    first = analyze("option", payload)
    assert first == analyze("option", payload)
    assert len(first["report_id"]) == 64
    assert first["report_id"] != analyze("option", payload | {"spot": 101})["report_id"]
    assert first["live_authorized"] is False


@pytest.mark.parametrize("operation", ["option", "option-portfolio", "order-lifecycle", "auto-quoting"])
def test_api_permissions_validation_and_size(monkeypatch, operation):
    app = FastAPI()
    app.middleware("http")(protect_api)
    app.include_router(router, prefix="/api/institutional")
    token = "i" * 32
    viewer = "v" * 32
    monkeypatch.setattr(settings, "API_OPERATOR_KEY_HASH", hashlib.sha256(token.encode()).hexdigest())
    monkeypatch.setattr(settings, "API_VIEWER_KEY_HASH", hashlib.sha256(viewer.encode()).hexdigest())
    client = TestClient(app)
    path = f"/api/institutional/{operation}"
    assert client.post(path, json={}).status_code == 401
    assert client.post(path, json={}, headers={"Authorization": f"Bearer {viewer}"}).status_code == 403
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(path, json={}, headers=headers).status_code == 422
    assert client.post(path, content="{broken", headers=headers).status_code == 422
    assert client.post(path, content=" " * 2_000_001, headers=headers).status_code == 413
    assert client.get("/api/institutional/capabilities", headers=headers).status_code == 200
    response = client.post(path, json=EXAMPLES[operation]["input"], headers=headers)
    assert response.status_code == 200
    assert response.json()["live_authorized"] is False


@pytest.mark.parametrize("operation", ["option", "option-portfolio", "order-lifecycle", "auto-quoting"])
def test_cli_writes_report_and_refuses_overwrite(tmp_path, operation):
    source = tmp_path / "input.json"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(EXAMPLES[operation]["input"]), encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve().parents[2] / "institutional_cli.py"),
               operation, str(source), "--output", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    original = output.read_bytes()
    assert json.loads(original)["operation"] == operation
    assert subprocess.run(command, capture_output=True).returncode == 2
    assert output.read_bytes() == original


EXAMPLES = json.loads((Path(__file__).resolve().parents[3] /
                      "frontend/src/data/institutional-examples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("operation", sorted(EXAMPLES))
def test_dashboard_examples_run_through_real_service(operation):
    report = analyze(operation, EXAMPLES[operation]["input"])
    assert report["operation"] == operation
    assert report["live_authorized"] is False
    json.dumps(report, allow_nan=False)
