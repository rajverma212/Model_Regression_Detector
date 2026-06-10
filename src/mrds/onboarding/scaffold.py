"""Generate a starter system prompt from a :class:`FeatureSpec` (pure).

The scaffold enumerates the declared output enums and demands strict JSON matching the
output schema. It is a starting point the user edits — not a finished prompt.
"""

from __future__ import annotations

import json

from mrds.features.spec import FeatureSpec, FieldType
from mrds.onboarding.inference import FeatureFamily, _coerce_family


def scaffold_prompt(spec: FeatureSpec, *, feature_type: str | FeatureFamily) -> str:
    """Return a non-blank system-prompt template for ``spec``."""
    family = _coerce_family(feature_type)
    verb = "Classify" if family is FeatureFamily.CLASSIFICATION else "Route"

    lines: list[str] = [f"{verb} the input below."]
    for field in spec.output_fields:
        if field.type is FieldType.ENUM:
            options = " | ".join(field.values)
            lines.append(f"- Choose a '{field.name}' from: {options}.")

    schema_example = {
        field.name: (field.values[0] if field.type is FieldType.ENUM and field.values else "...")
        for field in spec.output_fields
    }
    lines.append("")
    lines.append("Respond with ONLY a JSON object, no markdown fences and no extra text, matching:")
    lines.append(f"  {json.dumps(schema_example)}")
    return "\n".join(lines)
