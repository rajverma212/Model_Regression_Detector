"""Validate the GitHub Actions workflows: syntax, structure, and CLI integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CI = Path(".github/workflows/ci.yml")
EVAL = Path(".github/workflows/eval.yml")

REQUIRED_PATHS = (
    "prompts/**",
    "datasets/**",
    "src/mrds/features/**",
    "config/**",
)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_workflow_files_exist() -> None:
    assert CI.exists()
    assert EVAL.exists()


def test_workflows_are_valid_yaml_with_jobs() -> None:
    # safe_load raises on a syntax error; both must parse to a mapping with jobs.
    for path in (CI, EVAL):
        data = _load(path)
        assert isinstance(data, dict)
        assert "jobs" in data and data["jobs"]


def test_eval_filters_on_required_paths() -> None:
    text = EVAL.read_text(encoding="utf-8")
    for glob in REQUIRED_PATHS:
        assert glob in text, glob


def test_eval_uses_existing_cli_commands() -> None:
    text = EVAL.read_text(encoding="utf-8")
    assert "mrds evaluate" in text
    assert "mrds compare" in text
    assert "mrds promote-baseline" in text


def test_eval_uploads_report_artifacts() -> None:
    assert "upload-artifact" in EVAL.read_text(encoding="utf-8")


def test_eval_does_not_mask_compare_exit_code() -> None:
    # The gate relies on `mrds compare` failing the step; nothing may swallow it.
    text = EVAL.read_text(encoding="utf-8")
    assert "|| true" not in text
    assert "continue-on-error" not in text


def test_ci_runs_lint_format_and_tests() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "ruff check" in text
    assert "ruff format --check" in text
    assert "pytest" in text


def test_workflows_pin_python_311() -> None:
    for path in (CI, EVAL):
        assert '"3.11"' in path.read_text(encoding="utf-8")
