"""Tests for the prompt-management subsystem (models, loader, validation, registry)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mrds.prompts import (
    LoadedPrompt,
    PromptDefinition,
    PromptNotFoundError,
    PromptRegistry,
    PromptValidationError,
    compute_content_hash,
    load_prompt_file,
)
from mrds.prompts.errors import PromptError

REPO_PROMPT = Path("prompts/email_classifier/v1.yaml")

VALID_YAML = """
version: v1
created_at: 2026-05-29
description: A test prompt.
system_prompt: You are a classifier.
few_shot_examples:
  - input: hello
    output: world
tags: [test]
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    feature_dir = tmp_path / "email_classifier"
    feature_dir.mkdir(parents=True, exist_ok=True)
    path = feature_dir / name
    path.write_text(content, encoding="utf-8")
    return path


# -- loading + models -----------------------------------------------------------


def test_load_repo_sample_prompt() -> None:
    prompt = load_prompt_file(REPO_PROMPT)
    assert isinstance(prompt, LoadedPrompt)
    assert prompt.feature == "email_classifier"
    assert prompt.version == "v1"
    assert prompt.identity == "email_classifier:v1"
    assert prompt.definition.few_shot_examples  # has examples
    assert len(prompt.content_hash) == 64  # sha-256 hex


def test_feature_defaults_to_parent_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, "v1.yaml", VALID_YAML)
    assert load_prompt_file(path).feature == "email_classifier"


# -- hashing --------------------------------------------------------------------


def test_hash_is_deterministic(tmp_path: Path) -> None:
    path = _write(tmp_path, "v1.yaml", VALID_YAML)
    assert load_prompt_file(path).content_hash == load_prompt_file(path).content_hash


def test_hash_ignores_created_at_but_tracks_content() -> None:
    base = {
        "version": "v1",
        "created_at": date(2026, 1, 1),
        "description": "d",
        "system_prompt": "s",
    }
    same_content_other_date = PromptDefinition(**{**base, "created_at": date(2030, 12, 31)})
    changed_content = PromptDefinition(**{**base, "system_prompt": "different"})

    assert compute_content_hash(PromptDefinition(**base)) == compute_content_hash(
        same_content_other_date
    )
    assert compute_content_hash(PromptDefinition(**base)) != compute_content_hash(changed_content)


# -- validation of malformed files ----------------------------------------------


MALFORMED_PROMPTS = {
    "missing_description": "version: v1\ncreated_at: 2026-01-01\nsystem_prompt: s",
    "bad_version": "version: 1\ncreated_at: 2026-01-01\ndescription: d\nsystem_prompt: s",
    "blank_system_prompt": (
        "version: v1\ncreated_at: 2026-01-01\ndescription: d\nsystem_prompt: '   '"
    ),
    "extra_key": ("version: v1\ncreated_at: 2026-01-01\ndescription: d\nsystem_prompt: s\nbad: x"),
    "not_a_mapping": "just a string",
    "bad_date": "version: v1\ncreated_at: not-a-date\ndescription: d\nsystem_prompt: s",
    "malformed_yaml": "key: [unclosed",
}


@pytest.mark.parametrize("content", MALFORMED_PROMPTS.values(), ids=MALFORMED_PROMPTS.keys())
def test_malformed_prompts_raise(tmp_path: Path, content: str) -> None:
    path = _write(tmp_path, "bad.yaml", content)
    with pytest.raises(PromptValidationError):
        load_prompt_file(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PromptValidationError):
        load_prompt_file(tmp_path / "does_not_exist.yaml")


# -- registry -------------------------------------------------------------------


def test_registry_discovers_repo_prompts() -> None:
    registry = PromptRegistry.from_directory(Path("prompts"))
    assert "email_classifier" in registry.features()
    assert registry.versions("email_classifier") == ["v1"]
    assert registry.get("email_classifier", "v1").version == "v1"
    assert registry.get_latest("email_classifier").version == "v1"
    assert len(registry) >= 1


def test_registry_latest_picks_highest_version(tmp_path: Path) -> None:
    _write(tmp_path, "v1.yaml", VALID_YAML)
    _write(tmp_path, "v2.yaml", VALID_YAML.replace("version: v1", "version: v2"))
    registry = PromptRegistry.from_directory(tmp_path)
    assert registry.versions("email_classifier") == ["v1", "v2"]
    assert registry.get_latest("email_classifier").version == "v2"


def test_registry_unknown_lookups_raise(tmp_path: Path) -> None:
    _write(tmp_path, "v1.yaml", VALID_YAML)
    registry = PromptRegistry.from_directory(tmp_path)
    with pytest.raises(PromptNotFoundError):
        registry.get("email_classifier", "v9")
    with pytest.raises(PromptNotFoundError):
        registry.get_latest("nonexistent_feature")


def test_registry_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        PromptRegistry.from_directory(tmp_path / "nope")


def test_registry_rejects_duplicate_version(tmp_path: Path) -> None:
    registry = PromptRegistry(tmp_path)
    prompt = load_prompt_file(_write(tmp_path, "v1.yaml", VALID_YAML))
    registry.register(prompt)
    with pytest.raises(PromptError):
        registry.register(prompt)
