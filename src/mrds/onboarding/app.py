"""Onboarding Wizard v0 — a thin Streamlit UI over the onboarding core.

A five-step wizard (Identity → Upload → Review schema → Review/edit prompt →
Generate) that turns a name, family, labeled dataset, and instructions into a
validated feature bundle, using only ``infer_feature_spec`` / ``scaffold_prompt`` /
``write_feature_bundle``.

Run with: ``streamlit run src/mrds/onboarding/app.py``. Supports Classification and
Routing only. It does **not** evaluate, register, or globally discover the feature —
it just writes a bundle (see docs/onboarding-mvp-implementation-plan.md).
"""

from __future__ import annotations

import json

import streamlit as st

from mrds.features.spec import FieldType
from mrds.onboarding import (
    FeatureFamily,
    OnboardingError,
    infer_feature_spec,
    scaffold_prompt,
    write_feature_bundle,
)

_FAMILIES = [family.value for family in FeatureFamily]
_TOTAL_STEPS = 5

st.set_page_config(page_title="MRDS Feature Onboarding", layout="wide")
st.title("Feature Onboarding Wizard (v0)")
st.caption(
    "Classification & Routing only. Produces a spec + prompt + dataset bundle — no "
    "evaluation, registration, or discovery."
)

state = st.session_state
state.setdefault("step", 1)
state.setdefault("feature_name", "")
state.setdefault("feature_type", _FAMILIES[0])
state.setdefault("cases", None)
state.setdefault("spec", None)
state.setdefault("system_prompt", "")


def _goto(step: int) -> None:
    state["step"] = step
    st.rerun()


def _reset() -> None:
    for key in ("step", "feature_name", "feature_type", "cases", "spec", "system_prompt"):
        state.pop(key, None)
    st.rerun()


# Guard against landing on a later step without the data it needs.
if state["step"] >= 3 and state["spec"] is None:
    state["step"] = 1

st.progress((state["step"] - 1) / (_TOTAL_STEPS - 1))
st.markdown(f"**Step {state['step']} of {_TOTAL_STEPS}**")
st.divider()


# -- Step 1: Identity -----------------------------------------------------------
if state["step"] == 1:
    st.subheader("1 · Identity")
    name = st.text_input("Feature name", value=state["feature_name"], placeholder="support_router")
    family = st.selectbox("Feature type", _FAMILIES, index=_FAMILIES.index(state["feature_type"]))
    if st.button("Next ▶", type="primary"):
        if not name.strip():
            st.error("Feature name is required.")
        else:
            state["feature_name"] = name.strip()
            state["feature_type"] = family
            _goto(2)

# -- Step 2: Upload dataset -----------------------------------------------------
elif state["step"] == 2:
    st.subheader("2 · Upload dataset (JSON)")
    st.caption("A labeled set: cases of `input → expected_output`.")
    uploaded = st.file_uploader("Labeled dataset", type=["json"])

    raw: object | None = None
    if uploaded is not None:
        try:
            raw = json.loads(uploaded.getvalue().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            st.error(f"Could not parse JSON: {exc}")
            raw = None
        else:
            count = (
                len(raw["cases"])
                if isinstance(raw, dict) and "cases" in raw
                else (len(raw) if isinstance(raw, list) else 0)
            )
            st.info(f"Parsed {count} case(s).")

    back, nxt = st.columns(2)
    if back.button("◀ Back"):
        _goto(1)
    if nxt.button("Next ▶", type="primary", disabled=raw is None):
        try:
            spec = infer_feature_spec(
                raw, feature_name=state["feature_name"], feature_type=state["feature_type"]
            )
        except OnboardingError as exc:
            st.error(str(exc))
        else:
            state["cases"] = raw["cases"] if isinstance(raw, dict) else raw
            state["spec"] = spec
            _goto(3)

# -- Step 3: Review inferred schema --------------------------------------------
elif state["step"] == 3:
    spec = state["spec"]
    st.subheader("3 · Review inferred schema")

    st.markdown("**Inputs**")
    st.table(
        [{"field": f.name, "type": f.type.value, "required": f.required} for f in spec.input_fields]
    )

    st.markdown("**Outputs**")
    st.table(
        [
            {
                "field": f.name,
                "type": f.type.value,
                "values": ", ".join(f.values) if f.type is FieldType.ENUM else "",
                "required": f.required,
            }
            for f in spec.output_fields
        ]
    )

    st.markdown("**Scoring**")
    st.table([{"field": s.field, "scorer": s.scorer.value} for s in spec.scoring])
    st.caption(f"Segment field: **{spec.segment_field}**")
    st.info("v0 reviews the inferred schema; editing fields is not supported yet.")

    back, nxt = st.columns(2)
    if back.button("◀ Back"):
        _goto(2)
    if nxt.button("Next ▶", type="primary"):
        state["system_prompt"] = scaffold_prompt(spec, feature_type=state["feature_type"])
        _goto(4)

# -- Step 4: Review / edit prompt ----------------------------------------------
elif state["step"] == 4:
    st.subheader("4 · Review / edit prompt")
    st.caption("Edit the scaffolded instructions the model will follow.")
    edited = st.text_area("System prompt", value=state["system_prompt"], height=320)

    back, nxt = st.columns(2)
    if back.button("◀ Back"):
        _goto(3)
    if nxt.button("Next ▶", type="primary"):
        if not edited.strip():
            st.error("Instructions must not be blank.")
        else:
            state["system_prompt"] = edited
            _goto(5)

# -- Step 5: Generate bundle ----------------------------------------------------
elif state["step"] == 5:
    st.subheader("5 · Generate bundle")
    st.caption("Writes an isolated `<output dir>/<feature_name>/` bundle.")
    root = st.text_input("Output directory", value="features")

    back, gen = st.columns(2)
    if back.button("◀ Back"):
        _goto(4)
    if gen.button("Generate bundle", type="primary"):
        try:
            paths = write_feature_bundle(
                state["spec"],
                cases=state["cases"],
                system_prompt=state["system_prompt"],
                root=root,
            )
        except OnboardingError as exc:
            st.error(str(exc))
        else:
            st.success(f"Bundle generated for **{state['spec'].feature_name}**.")
            st.code(
                f"{paths.feature_yaml}\n{paths.prompt_yaml}\n{paths.dataset_json}",
                language="text",
            )
            st.caption(
                "Reuses the spec-driven layer. The feature is not registered or run (by design)."
            )

    st.divider()
    if st.button("Start over"):
        _reset()
