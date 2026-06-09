"""Dynamic Pydantic model + enum generation from a :class:`FeatureSpec`.

Turns declarative field lists into real Pydantic models (and ``StrEnum`` types for
categorical fields) at load time, so a spec-driven feature exposes ordinary
``input_model`` / ``output_model`` classes — exactly what the dataset resolver and
the LLM client already expect. No core code is involved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, create_model

from mrds.features.spec.spec import FeatureSpec, FieldSpec, FieldType, SpecError

_SCALAR_TYPES: dict[FieldType, type] = {
    FieldType.STRING: str,
    FieldType.INTEGER: int,
    FieldType.NUMBER: float,
    FieldType.BOOLEAN: bool,
}


def _pascal(name: str) -> str:
    """``ticket_router`` -> ``TicketRouter`` (for generated class names)."""
    parts = [p for p in re.split(r"[^0-9a-zA-Z]+", name) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Feature"


def build_enum(name: str, values: Sequence[str]) -> type[StrEnum]:
    """Build a ``StrEnum`` whose member values are exactly ``values``."""
    members: dict[str, str] = {}
    used: set[str] = set()
    for value in values:
        member = re.sub(r"\W+", "_", value).strip("_").upper() or "VALUE"
        candidate, suffix = member, 2
        while candidate in used:
            candidate, suffix = f"{member}_{suffix}", suffix + 1
        used.add(candidate)
        members[candidate] = value
    return StrEnum(name, members)  # type: ignore[return-value]


def _field_type(field: FieldSpec, model_name: str) -> type:
    if field.type is FieldType.ENUM:
        return build_enum(f"{model_name}_{_pascal(field.name)}", field.values)
    scalar = _SCALAR_TYPES.get(field.type)
    if scalar is None:  # pragma: no cover - guarded by FieldSpec validation
        raise SpecError(f"unsupported field type: {field.type}")
    return scalar


def build_model(model_name: str, fields: Sequence[FieldSpec]) -> type[BaseModel]:
    """Build a Pydantic model (``extra='forbid'``) from field declarations."""
    definitions: dict[str, tuple[object, object]] = {}
    for field in fields:
        python_type = _field_type(field, model_name)
        if field.required:
            definitions[field.name] = (python_type, ...)
        else:
            definitions[field.name] = (python_type | None, None)
    return create_model(  # type: ignore[call-overload, no-any-return]
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **definitions,
    )


def build_input_model(spec: FeatureSpec) -> type[BaseModel]:
    """Generate the input model for a spec."""
    return build_model(f"{_pascal(spec.feature_name)}Input", spec.input_fields)


def build_output_model(spec: FeatureSpec) -> type[BaseModel]:
    """Generate the output model for a spec."""
    return build_model(f"{_pascal(spec.feature_name)}Output", spec.output_fields)
