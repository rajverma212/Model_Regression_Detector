"""Tests for the HTTP API layer (``mrds.api``).

The API is a thin, feature-agnostic wrapper over the existing read/promote paths, so
these tests drive it through a :class:`TestClient` against a temp database seeded with
the deterministic, offline demo narrative (no OpenAI). They assert the wire contract the
web frontend depends on: enriched fleet/run payloads, run-vs-run comparison, the
root-cause attribution, the baseline-promotion guard, and onboarding inference.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrds.api.app import create_app, get_llm_client, get_platform_root, get_session
from mrds.api.runtime import ApiSession
from mrds.db import EvaluationStore, SqliteBackend, open_database
from mrds.demo import seed_demo
from mrds.llm.base import LLMMessage, LLMResult


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
        session = ApiSession(SqliteBackend(db_path))
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


# --- End-to-end activation -----------------------------------------------------


def _case(case_id: str, text: str, category: str) -> dict[str, object]:
    return {"id": case_id, "input": {"text": text}, "expected_output": {"category": category}}


_ACTIVATE_CASES = [
    _case("a1", "please refund my charge", "billing"),
    _case("a2", "send me an invoice", "billing"),
    _case("a3", "the app crashes on launch", "technical"),
    _case("a4", "error on the login page", "technical"),
    _case("a5", "reset my password", "account"),
    _case("a6", "change my email address", "account"),
]
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _ACTIVATE_CASES}


class _ActivateStub:
    """Deterministic offline LLM: returns the labeled category for each known input."""

    def parse_structured(self, *, model: str, messages, schema):  # type: ignore[no-untyped-def]
        last = messages[-1]
        text = last.content if isinstance(last, LLMMessage) else last["content"]
        label = _ORACLE.get(text, "billing")
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=6,
            output_tokens=2,
            total_tokens=8,
        )


@pytest.fixture
def activation_client(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient with an empty DB, a writable platform root, and a stub LLM."""
    db_path = tmp_path / "eval.db"
    open_database(db_path).close()  # bootstrap schema on an empty DB
    platform_root = tmp_path / "platform"
    platform_root.mkdir()

    app = create_app()

    def _session() -> Iterator[ApiSession]:
        session = ApiSession(SqliteBackend(db_path))
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_platform_root] = lambda: platform_root
    app.dependency_overrides[get_llm_client] = lambda: _ActivateStub()
    with TestClient(app) as test_client:
        test_client.platform_root = platform_root  # type: ignore[attr-defined]
        yield test_client


def test_activate_is_end_to_end_and_appears_in_mission_control(
    activation_client: TestClient,
) -> None:
    assert activation_client.get("/api/features").json() == []  # nothing onboarded yet

    resp = activation_client.post(
        "/api/onboarding/activate",
        json={
            "feature_name": "support_activate",
            "feature_type": "classification",
            "cases": _ACTIVATE_CASES,
            "system_prompt": "Classify the support message into one category. Respond as JSON.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Success response carries the contract the wizard needs.
    assert body["feature"] == "support_activate"
    assert body["run_id"]
    assert isinstance(body["baseline_id"], int)
    summary = body["summary"]
    assert summary["total_cases"] == 6
    assert 0.0 <= summary["pass_rate"] <= 1.0

    # Mission Control shows the feature immediately, with the promoted baseline.
    fleet = activation_client.get("/api/features").json()
    assert [f["feature"] for f in fleet] == ["support_activate"]
    overview = activation_client.get("/api/features/support_activate").json()
    assert overview["has_baseline"] is True
    assert overview["run_count"] == 1

    baseline = activation_client.get("/api/features/support_activate/baseline").json()
    assert baseline["active"]["id"] == body["baseline_id"]
    assert baseline["active"]["run_uuid"] == body["run_id"]


def test_activate_rejects_duplicate_feature(activation_client: TestClient) -> None:
    payload = {
        "feature_name": "support_activate",
        "feature_type": "classification",
        "cases": _ACTIVATE_CASES,
        "system_prompt": "Classify the support message. Respond as JSON.",
    }
    assert activation_client.post("/api/onboarding/activate", json=payload).status_code == 200
    dup = activation_client.post("/api/onboarding/activate", json=payload)
    assert dup.status_code == 400
    assert "already" in dup.json()["detail"].lower()


def test_activate_succeeds_with_another_feature_in_shared_root(
    activation_client: TestClient,
) -> None:
    """Regression test for the dataset-discovery bug: a *different* feature already living
    in the shared platform root (different schema) must not break a new activation."""
    # Pre-seed a foreign feature's dataset under the shared root, with a schema that does
    # NOT match the feature being activated (input `email_text`, not `text`). Before the
    # fix, run_first_evaluation validated this against the new feature's models → 500.
    platform_root: Path = activation_client.platform_root  # type: ignore[attr-defined]
    foreign = platform_root / "datasets" / "email_like"
    foreign.mkdir(parents=True)
    (foreign / "v1.json").write_text(
        json.dumps(
            {
                "version": "v1",
                "created_at": "2026-01-01",
                "description": "A foreign feature with a different schema.",
                "cases": [
                    {
                        "id": "e1",
                        "input": {"email_text": "I was charged twice."},
                        "expected_output": {"category": "billing", "summary": "Double charge."},
                        "expected_difficulty": "easy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    resp = activation_client.post(
        "/api/onboarding/activate",
        json={
            "feature_name": "support_activate",
            "feature_type": "classification",
            "cases": _ACTIVATE_CASES,
            "system_prompt": "Classify the support message. Respond as JSON.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["total_cases"] == 6
    assert isinstance(body["baseline_id"], int)

    fleet = activation_client.get("/api/features").json()
    assert [f["feature"] for f in fleet] == ["support_activate"]
    overview = activation_client.get("/api/features/support_activate").json()
    assert overview["has_baseline"] is True
    assert overview["run_count"] == 1


def _activate_app(db_path: Path, platform_root: Path, *, with_client: bool) -> object:
    """Build an app wired to a temp DB + given platform root (and optional stub LLM)."""
    app = create_app()

    def _session() -> Iterator[ApiSession]:
        session = ApiSession(SqliteBackend(db_path))
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_platform_root] = lambda: platform_root
    if with_client:
        app.dependency_overrides[get_llm_client] = lambda: _ActivateStub()
    return app


def test_activate_fails_fast_without_llm_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No key + no injected client → a clear 422 *before* anything is persisted."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_path = tmp_path / "eval.db"
    open_database(db_path).close()
    platform_root = tmp_path / "platform"
    platform_root.mkdir()

    app = _activate_app(db_path, platform_root, with_client=False)  # real (None) client → no key
    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/activate",
            json={
                "feature_name": "nokey",
                "feature_type": "classification",
                "cases": _ACTIVATE_CASES,
                "system_prompt": "Classify. JSON out.",
            },
        )
    assert resp.status_code == 422
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]
    assert not (platform_root / "specs").exists()  # nothing persisted


def test_activate_returns_clear_error_when_root_unwritable(tmp_path: Path) -> None:
    """A non-writable platform root → a clear JSON 503, not an opaque plain-text 500."""
    db_path = tmp_path / "eval.db"
    open_database(db_path).close()
    # Parent is a *file*, so creating any directory under it raises OSError for everyone
    # (robust across CI-as-root, unlike chmod).
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    platform_root = blocker / "sub"

    app = _activate_app(db_path, platform_root, with_client=True)  # stub passes the key check
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/api/onboarding/activate",
            json={
                "feature_name": "readonly",
                "feature_type": "classification",
                "cases": _ACTIVATE_CASES,
                "system_prompt": "Classify. JSON out.",
            },
        )
    assert resp.status_code == 503
    assert "not writable" in resp.json()["detail"]
