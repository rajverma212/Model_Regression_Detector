"""Phase 1 — install a generated bundle into discoverable locations.

Copies a validated onboarding bundle into the platform layout under ``root``::

    root/specs/<name>.yaml          (installed spec, scanned by spec discovery)
    root/prompts/<name>/v1.yaml     (shared prompt root, scanned by the engine)
    root/datasets/<name>/v1.json    (shared dataset root, scanned by the engine)

Validates the bundle first (the LLM-free schema gate) and refuses to overwrite an
already-installed feature. Pure file I/O — no registry or engine involvement.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from mrds.activation.errors import ActivationError
from mrds.features.spec import FeatureSpec, build_input_model, build_output_model, load_feature_spec
from mrds.prompts.registry import PromptRegistry


@dataclass(frozen=True)
class InstalledPaths:
    """Where a bundle's artifacts were installed."""

    feature_name: str
    spec: Path
    prompt: Path
    dataset: Path


def _validate_bundle(spec: FeatureSpec, bundle_dir: Path, dataset_path: Path) -> None:
    """Re-validate the bundle before installing it (schema gate, no LLM)."""
    input_model = build_input_model(spec)
    output_model = build_output_model(spec)
    try:
        raw = json.loads(dataset_path.read_text(encoding="utf-8"))
        cases: Sequence[dict] = raw["cases"] if isinstance(raw, dict) else raw
        for case in cases:
            input_model.model_validate(case["input"])
            output_model.model_validate(case["expected_output"])
    except (KeyError, TypeError, ValidationError, json.JSONDecodeError) as exc:
        raise ActivationError(f"dataset does not match the spec: {exc}") from exc

    try:
        PromptRegistry.from_directory(bundle_dir / "prompts").get_latest(spec.feature_name)
    except Exception as exc:  # noqa: BLE001 - any prompt-load failure means an invalid bundle
        raise ActivationError(f"invalid prompt in bundle: {exc}") from exc


def install_bundle(bundle_dir: str | Path, *, root: str | Path) -> InstalledPaths:
    """Install a generated bundle under ``root``; validate first, never overwrite."""
    bundle_dir = Path(bundle_dir)
    root = Path(root)

    feature_yaml = bundle_dir / "feature.yaml"
    if not feature_yaml.is_file():
        raise ActivationError(f"no feature.yaml in bundle: {bundle_dir}")
    try:
        spec = load_feature_spec(feature_yaml)
    except Exception as exc:  # noqa: BLE001 - surface any spec parse/validation failure
        raise ActivationError(f"invalid feature.yaml: {exc}") from exc

    name = spec.feature_name
    src_prompt = bundle_dir / "prompts" / name / "v1.yaml"
    src_dataset = bundle_dir / "datasets" / name / "v1.json"
    if not src_prompt.is_file() or not src_dataset.is_file():
        raise ActivationError(f"bundle for '{name}' is missing its prompt or dataset")

    _validate_bundle(spec, bundle_dir, src_dataset)

    spec_target = root / "specs" / f"{name}.yaml"
    prompt_target = root / "prompts" / name / "v1.yaml"
    dataset_target = root / "datasets" / name / "v1.json"
    for target in (spec_target, prompt_target, dataset_target):
        if target.exists():
            raise ActivationError(f"feature '{name}' is already installed ({target})")

    created: list[Path] = []
    try:
        for target, source in (
            (spec_target, feature_yaml),
            (prompt_target, src_prompt),
            (dataset_target, src_dataset),
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            created.append(target)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return InstalledPaths(
        feature_name=name, spec=spec_target, prompt=prompt_target, dataset=dataset_target
    )
