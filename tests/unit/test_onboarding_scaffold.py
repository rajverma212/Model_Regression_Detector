"""Tests for the prompt scaffolder."""

from __future__ import annotations

from datetime import date

from mrds.onboarding import infer_feature_spec, scaffold_prompt
from mrds.prompts.models import PromptDefinition

_RAW = {
    "cases": [
        {"id": "c1", "input": {"text": "refund"}, "expected_output": {"category": "billing"}},
        {"id": "c2", "input": {"text": "crash"}, "expected_output": {"category": "technical"}},
        {"id": "c3", "input": {"text": "login"}, "expected_output": {"category": "account"}},
    ]
}


def test_scaffold_mentions_every_enum_value() -> None:
    spec = infer_feature_spec(_RAW, feature_name="cls", feature_type="classification")
    prompt = scaffold_prompt(spec, feature_type="classification")
    assert prompt.strip()
    for value in ("billing", "technical", "account"):
        assert value in prompt
    assert "JSON" in prompt


def test_scaffold_output_is_valid_prompt_body() -> None:
    spec = infer_feature_spec(_RAW, feature_name="cls", feature_type="classification")
    system_prompt = scaffold_prompt(spec, feature_type="classification")
    # The scaffolded text is accepted as a real prompt definition.
    definition = PromptDefinition.model_validate(
        {
            "version": "v1",
            "created_at": date.today().isoformat(),
            "description": "scaffolded",
            "system_prompt": system_prompt,
        }
    )
    assert definition.system_prompt == system_prompt


def test_routing_scaffold_uses_route_verb() -> None:
    spec = infer_feature_spec(_RAW, feature_name="cls", feature_type="routing")
    assert scaffold_prompt(spec, feature_type="routing").startswith("Route")
