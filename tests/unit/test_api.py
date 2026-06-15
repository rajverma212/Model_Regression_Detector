"""Tests for the HTTP API layer (``mrds.api``).

The API is a thin, feature-agnostic wrapper over the existing read/promote paths, so
these tests drive it through a :class:`TestClient` against a temp database seeded with
the deterministic, offline demo narrative (no OpenAI). They assert the wire contract the
web frontend depends on: enriched fleet/run payloads, run-vs-run comparison, the
root-cause attribution, the baseline-promotion guard, and onboarding inference.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrds.api.app import create_app, get_session
from mrds.api.runtime import ApiSession
from mrds.db import EvaluationStore, open_database
from mrds.demo import seed_demo


@pytest.fixture(scope="session")
def _seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Seed the demo history once; tests copy this template for per-test isolation.

    Seeding runs the real (offline) eval pipeline for several runs, so doing it once
    and copying the checkpointed file keeps the suite fast.
    """
    path = tmp_path_factory.mktemp("seed") / "template.db"
    db = open_database(path)
    seed_demo(EvaluationStore(db))
    db.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold WAL into the .db file
    db.close()
    return path


@pytest.fixture
def client(_seeded_db: Path, tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient bound to a fresh per-test copy of the seeded database."""
    db_path = tmp_path / "eval.db"
    shutil.copy(_seeded_db, db_path)

    app = create_app()

    def _override() -> Iterator[ApiSession]:
        session = ApiSession(db_path)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as test_client:
        yield test_client


def _latest_critical_run(client: TestClient, feature: str) -> str:
    runs = client.get(f"/api/features/{feature}/runs").json()
    for run in runs:
        if run["health"] == "critical":
            return run["run_uuid"]
    return runs[0]["run_uuid"]


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_features_fleet_payload(client: TestClient) -> None:
    fleet = client.get("/api/features").json()
    names = {f["feature"] for f in fleet}
    assert {"email_classifier", "ticket_router"} <= names

    email = next(f for f in fleet if f["feature"] == "email_classifier")
    assert email["display_name"] == "Email Classifier"
    assert email["health"] == "critical"  # the demo ends on a critical regression
    assert email["has_baseline"] is True
    assert email["baseline_delta"] is not None and email["baseline_delta"] < 0
    assert len(email["sparkline"]) == email["run_count"]


def test_unknown_feature_404(client: TestClient) -> None:
    assert client.get("/api/features/nope").status_code == 404


def test_run_detail_is_verdict_first_and_explains_failures(client: TestClient) -> None:
    run_uuid = _latest_critical_run(client, "email_classifier")
    detail = client.get(f"/api/runs/{run_uuid}").json()

    # Verdict-first: a plain-language headline + health, baseline context.
    assert detail["verdict"]["health"] == "critical"
    assert "baseline" in detail["verdict"]["headline"]
    assert detail["baseline"]["pass_rate"] is not None

    # Per-case explainability: failing cases carry the actual vs expected and scorer detail.
    failing = [c for c in detail["cases"] if not c["passed"]]
    assert failing, "expected at least one failing case on a critical run"
    case = failing[0]
    assert case["actual"] is not None
    assert case["summary"]  # one-line plain-English verdict
    assert any(not s["passed"] and s["detail"] for s in case["scorers"])

    # Segment breakdown is present (feature-agnostic discovery).
    assert detail["metrics"]["segment_field"] == "category"
    assert detail["metrics"]["segments"]


def test_unknown_run_404(client: TestClient) -> None:
    assert client.get("/api/runs/deadbeef").status_code == 404


def test_compare_two_runs(client: TestClient) -> None:
    runs = client.get("/api/features/email_classifier/runs").json()
    newest = runs[0]["run_uuid"]
    oldest = runs[-1]["run_uuid"]
    cmp = client.get(f"/api/compare?a={oldest}&b={newest}").json()
    assert cmp["severity"] in {"pass", "warning", "critical"}
    assert cmp["comparisons"]
    # Every comparison carries a humanized label for the UI.
    assert all(c["label"] for c in cmp["comparisons"])


def test_regressions_root_cause_maps_metric_to_cases(client: TestClient) -> None:
    run_uuid = _latest_critical_run(client, "email_classifier")
    reg = client.get(f"/api/runs/{run_uuid}/regressions").json()
    assert reg["has_baseline"] is True
    assert reg["comparison"]["regressions"]

    # The pass_rate regression must attribute to the specific failing cases.
    root = reg["root_cause"]
    assert "pass_rate" in root
    assert len(root["pass_rate"]) >= 1
    assert all("actual" in case for case in root["pass_rate"])


def test_promote_guard_refuses_regressed_run_without_force(client: TestClient) -> None:
    run_uuid = _latest_critical_run(client, "email_classifier")
    before = client.get("/api/features/email_classifier/baseline").json()["active"]["run_uuid"]

    resp = client.post(
        "/api/features/email_classifier/baseline/promote",
        json={"run_uuid": run_uuid},
    ).json()
    assert resp["promoted"] is False
    assert resp["eligibility"]["reasons"]

    after = client.get("/api/features/email_classifier/baseline").json()["active"]["run_uuid"]
    assert before == after  # baseline untouched


def test_promote_with_force_overrides(client: TestClient) -> None:
    run_uuid = _latest_critical_run(client, "email_classifier")
    resp = client.post(
        "/api/features/email_classifier/baseline/promote",
        json={"run_uuid": run_uuid, "force": True},
    ).json()
    assert resp["promoted"] is True
    active = client.get("/api/features/email_classifier/baseline").json()["active"]
    assert active["run_uuid"] == run_uuid


def test_onboarding_infers_schema_from_dataset(client: TestClient) -> None:
    resp = client.post(
        "/api/onboarding/infer",
        json={
            "feature_name": "sentiment",
            "feature_type": "classification",
            "cases": [
                {
                    "id": "s1",
                    "input": {"text": "love it"},
                    "expected_output": {"sentiment": "positive"},
                },
                {
                    "id": "s2",
                    "input": {"text": "hate it"},
                    "expected_output": {"sentiment": "negative"},
                },
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    output = body["spec"]["output_fields"][0]
    assert output["type"] == "enum"
    assert set(output["values"]) == {"negative", "positive"}
    assert "JSON" in body["prompt"]


def test_onboarding_rejects_unlabeled_dataset(client: TestClient) -> None:
    resp = client.post(
        "/api/onboarding/infer",
        json={
            "feature_name": "freeform",
            "feature_type": "classification",
            "cases": [
                {
                    "id": "f1",
                    "input": {"text": "hi"},
                    # A long free-text output is classified STRING (not a short enum label),
                    # so there is nothing categorical to grade with exact_match.
                    "expected_output": {
                        "reply": "Hello there, thanks so much for reaching out to our team today!"
                    },
                }
            ],
        },
    )
    assert resp.status_code == 400  # no categorical output to grade with exact_match


def test_dataset_explorer_payload(client: TestClient) -> None:
    data = client.get("/api/features/email_classifier/dataset").json()
    assert data["case_count"] > 0
    assert data["segment_field"] == "category"
    assert data["coverage"]["by_category"]
    assert all("expected" in c for c in data["cases"])
