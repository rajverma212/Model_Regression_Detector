"""Integration tests for the wired CLI commands (OpenAI faked, in-memory DB)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from mrds.cli.main import build_parser, main
from mrds.cli.runtime import CliRuntime
from mrds.core.interfaces import ScoreResult
from mrds.core.registry import FeatureRegistry
from mrds.datasets.models import Difficulty
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore, open_database
from mrds.evaluation import EvaluationEngine
from mrds.evaluation.models import (
    AggregateMetrics,
    CaseResult,
    EvaluationResult,
    LatencyStats,
    ScorerStats,
    TokenStats,
)
from mrds.features.email_classifier import (
    EmailCategory,
    EmailClassificationOutput,
    EmailClassifierFeature,
)
from mrds.llm.base import LLMMessage, LLMResult
from mrds.prompts.registry import PromptRegistry
from mrds.regression import RegressionDetector
from mrds.reporting import ReportBuilder

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


class ConstantEmailClient:
    """A fake structured client returning a fixed classification (no network)."""

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type[BaseModel]
    ) -> LLMResult[EmailClassificationOutput]:
        out = EmailClassificationOutput(
            category=EmailCategory.BILLING, summary="A constant classification result."
        )
        return LLMResult(parsed=out, model=model, input_tokens=5, output_tokens=3, total_tokens=8)


def _runtime() -> CliRuntime:
    prompts = PromptRegistry.from_directory(Path("prompts"))
    # Default (registry-based) resolver — the datasets dir is multi-feature.
    datasets = DatasetRegistry.from_directory(Path("datasets"))
    feature = EmailClassifierFeature(client=ConstantEmailClient(), prompt_registry=prompts)
    features = FeatureRegistry()
    features.register(feature)
    engine = EvaluationEngine(features=features, prompts=prompts, datasets=datasets)
    return CliRuntime(
        store=EvaluationStore(open_database(":memory:")),
        engine=engine,
        detector=RegressionDetector(),
        reporter=ReportBuilder(),
    )


def _persist_result(rt: CliRuntime, run_id: str, *, cat_mean: float, pass_rate: float) -> str:
    """Persist a controlled EvaluationResult directly (bypassing the engine)."""
    result = EvaluationResult(
        run_id=run_id,
        feature="email_classifier",
        prompt_version="v1",
        prompt_hash="ph1",
        dataset_version="v1",
        dataset_hash="dh1",
        model="gpt-4o-mini",
        start_time=NOW,
        end_time=NOW,
        duration_seconds=1.0,
        aggregate_metrics=AggregateMetrics(
            total_cases=10,
            passed=int(pass_rate * 10),
            failed=10 - int(pass_rate * 10),
            errored=0,
            pass_rate=pass_rate,
            scorers={
                "category_match": ScorerStats(
                    name="category_match",
                    mean_score=cat_mean,
                    pass_rate=cat_mean,
                    passed=9,
                    count=10,
                )
            },
            segments={},
            segment_field=None,
            latency=LatencyStats(
                count=10, total_ms=100, mean_ms=10, min_ms=8, p50_ms=10, p95_ms=15, max_ms=20
            ),
            tokens=TokenStats(
                total_tokens=80,
                total_input_tokens=50,
                total_output_tokens=30,
                mean_tokens_per_case=8.0,
            ),
        ),
        per_case_results=[
            CaseResult(
                case_id="c-1",
                expected_difficulty=Difficulty.EASY,
                input={"email_text": "hi"},
                expected_output={"category": "billing", "summary": "x"},
                actual_output={"category": "billing", "summary": "x"},
                scores=[ScoreResult(name="category_match", score=cat_mean, passed=cat_mean >= 0.5)],
                passed=cat_mean >= 0.5,
                latency_ms=10.0,
                total_tokens=8,
            )
        ],
    )
    rt.store.save_evaluation(result)
    return run_id


# -- parser-level ---------------------------------------------------------------


def test_no_command_prints_help() -> None:
    assert main([], runtime=_runtime()) == 0


def test_version_flag_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_all_commands_registered() -> None:
    parser = build_parser()
    action = next(a for a in parser._actions if a.dest == "command")
    assert {"evaluate", "compare", "report", "promote-baseline"} <= set(action.choices or {})


def test_evaluate_requires_feature() -> None:
    with pytest.raises(SystemExit):  # argparse rejects missing required --feature
        main(["evaluate"], runtime=_runtime())


# -- evaluate -------------------------------------------------------------------


def test_evaluate_runs_persists_and_prints_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    rt = _runtime()
    code = main(
        [
            "evaluate",
            "--feature",
            "email_classifier",
            "--max-cases",
            "5",
            "--segment-field",
            "category",
            "--triggered-by",
            "ci",
        ],
        runtime=rt,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "run_id:" in out
    uuid = rt.store.latest_run_uuid("email_classifier")
    assert uuid is not None
    restored = rt.store.get_evaluation_result(uuid)
    assert restored is not None
    assert restored.aggregate_metrics.total_cases == 5


# -- compare --------------------------------------------------------------------


def test_compare_without_baseline_is_ok(capsys: pytest.CaptureFixture[str]) -> None:
    rt = _runtime()
    _persist_result(rt, "run-1", cat_mean=0.9, pass_rate=0.9)
    code = main(["compare", "--feature", "email_classifier", "--no-report"], runtime=rt)
    assert code == 0
    assert "nothing to compare" in capsys.readouterr().out


def test_compare_blocking_returns_exit_1(capsys: pytest.CaptureFixture[str]) -> None:
    rt = _runtime()
    _persist_result(rt, "base-1", cat_mean=0.95, pass_rate=0.95)
    rt.store.promote_baseline("base-1", promoted_by="t")
    _persist_result(rt, "cand-1", cat_mean=0.70, pass_rate=0.70)  # big drop

    code = main(
        ["compare", "--feature", "email_classifier", "--run", "cand-1", "--no-report"],
        runtime=rt,
    )
    assert code == 1
    # The regression was persisted.
    cand_id = rt.store.runs.get_by_uuid("cand-1").id
    assert rt.store.regressions.list_for_run(cand_id)


def test_compare_no_regression_returns_zero() -> None:
    rt = _runtime()
    _persist_result(rt, "base-1", cat_mean=0.90, pass_rate=0.90)
    rt.store.promote_baseline("base-1", promoted_by="t")
    _persist_result(rt, "cand-1", cat_mean=0.92, pass_rate=0.92)  # improvement
    code = main(
        ["compare", "--feature", "email_classifier", "--run", "cand-1", "--no-report"],
        runtime=rt,
    )
    assert code == 0


def test_compare_writes_report(tmp_path: Path) -> None:
    rt = _runtime()
    _persist_result(rt, "base-1", cat_mean=0.95, pass_rate=0.95)
    rt.store.promote_baseline("base-1", promoted_by="t")
    _persist_result(rt, "cand-1", cat_mean=0.80, pass_rate=0.80)
    main(
        [
            "compare",
            "--feature",
            "email_classifier",
            "--run",
            "cand-1",
            "--report-dir",
            str(tmp_path),
        ],
        runtime=rt,
    )
    assert (tmp_path / "email_classifier" / "cand-1.regression.html").exists()
    assert (tmp_path / "email_classifier" / "cand-1.regression.md").exists()


# -- report ---------------------------------------------------------------------


def test_report_writes_html_and_markdown(tmp_path: Path) -> None:
    rt = _runtime()
    _persist_result(rt, "run-1", cat_mean=0.9, pass_rate=0.9)
    code = main(["report", "--run", "run-1", "--output-dir", str(tmp_path)], runtime=rt)
    assert code == 0
    assert (tmp_path / "email_classifier" / "run-1.html").exists()
    assert (tmp_path / "email_classifier" / "run-1.md").exists()


def test_report_unknown_run_errors() -> None:
    rt = _runtime()
    assert main(["report", "--run", "missing"], runtime=rt) == 2


# -- promote-baseline -----------------------------------------------------------


def test_promote_baseline_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    rt = _runtime()
    _persist_result(rt, "run-1", cat_mean=0.9, pass_rate=0.9)
    code = main(["promote-baseline", "--run", "run-1", "--promoted-by", "ci"], runtime=rt)
    assert code == 0
    assert "Promoted run run-1" in capsys.readouterr().out
    active = rt.store.baselines.get_active("email_classifier")
    assert active is not None and active.run_id == rt.store.runs.get_by_uuid("run-1").id


def test_promote_blocks_worse_run_without_force() -> None:
    rt = _runtime()
    _persist_result(rt, "base-1", cat_mean=0.95, pass_rate=0.95)
    rt.store.promote_baseline("base-1", promoted_by="t")
    _persist_result(rt, "cand-1", cat_mean=0.70, pass_rate=0.70)

    assert main(["promote-baseline", "--run", "cand-1"], runtime=rt) == 2  # ineligible
    assert main(["promote-baseline", "--run", "cand-1", "--force"], runtime=rt) == 0  # forced
    active = rt.store.baselines.get_active("email_classifier")
    assert active.run_id == rt.store.runs.get_by_uuid("cand-1").id


def test_promote_unknown_run_errors() -> None:
    rt = _runtime()
    assert main(["promote-baseline", "--run", "nope"], runtime=rt) == 2
