"""Create-a-Feature wizard — a thin Streamlit UI over the onboarding + activation cores.

A seven-step lifecycle that turns a name, family, labeled dataset, and instructions into
a live MRDS feature: Identity → Upload → Review schema → Review/edit prompt → Generate
bundle → **Activate** → **Run first evaluation** (with an inline results summary and a
link into the dashboard).

Steps 1–5 use the onboarding core (``infer_feature_spec`` / ``scaffold_prompt`` /
``write_feature_bundle``); Steps 6–7 use the activation lifecycle (``activate_bundle`` /
``run_first_evaluation``). Supports Classification and Routing only. Running an evaluation
requires ``ANTHROPIC_API_KEY``; without it, Step 7 shows the CLI fallback. See
docs/unified-platform-flow.md.

Run with: ``streamlit run src/mrds/onboarding/app.py``.
"""

from __future__ import annotations

import json

import streamlit as st

from mrds.activation import ActivationError
from mrds.activation.lifecycle import activate_bundle, run_first_evaluation
from mrds.config.settings import get_settings
from mrds.db import EvaluationStore, open_database
from mrds.features.spec import FieldType
from mrds.onboarding import (
    FeatureFamily,
    OnboardingError,
    infer_feature_spec,
    scaffold_prompt,
    write_feature_bundle,
)

_FAMILIES = [family.value for family in FeatureFamily]
_TOTAL_STEPS = 7

st.set_page_config(page_title="MRDS Feature Onboarding", layout="wide")
st.title("Create a Feature")
st.caption("Classification & Routing — create, activate, and run a first evaluation, end to end.")

state = st.session_state
_STATE_KEYS = (
    "step",
    "feature_name",
    "feature_type",
    "cases",
    "spec",
    "system_prompt",
    "bundle_dir",
    "installed",
    "eval_result",
)
state.setdefault("step", 1)
state.setdefault("feature_name", "")
state.setdefault("feature_type", _FAMILIES[0])
state.setdefault("cases", None)
state.setdefault("spec", None)
state.setdefault("system_prompt", "")
state.setdefault("bundle_dir", None)
state.setdefault("installed", None)
state.setdefault("eval_result", None)


def _goto(step: int) -> None:
    state["step"] = step
    st.rerun()


def _reset() -> None:
    for key in _STATE_KEYS:
        state.pop(key, None)
    st.rerun()


# Guard against landing on a step without the data it needs.
if state["step"] >= 3 and state["spec"] is None:
    state["step"] = 1
if state["step"] >= 6 and state["bundle_dir"] is None:
    state["step"] = 1
if state["step"] == 7 and state["installed"] is None:
    state["step"] = 6

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
    st.caption("Writes the feature's spec, prompt, and dataset to a bundle.")
    out_dir = st.text_input("Output directory", value="features")

    back, gen = st.columns(2)
    if back.button("◀ Back"):
        _goto(4)
    if gen.button("Generate bundle", type="primary"):
        try:
            paths = write_feature_bundle(
                state["spec"],
                cases=state["cases"],
                system_prompt=state["system_prompt"],
                root=out_dir,
            )
        except OnboardingError as exc:
            st.error(str(exc))
        else:
            state["bundle_dir"] = str(paths.bundle_dir)
            _goto(6)

# -- Step 6: Activate feature ---------------------------------------------------
elif state["step"] == 6:
    st.subheader("6 · Activate feature")
    name = state["spec"].feature_name
    st.success(f"**{name}** is ready.")
    st.caption("Make it part of MRDS — install its files and register it (one step).")

    back, act = st.columns(2)
    if back.button("◀ Back"):
        _goto(5)
    if act.button("Activate feature", type="primary"):
        try:
            state["installed"] = activate_bundle(state["bundle_dir"], root=".")
        except ActivationError as exc:
            st.error(f"Activation failed: {exc}")
        else:
            _goto(7)

    st.divider()
    if st.button("Start over"):
        _reset()

# -- Step 7: Run first evaluation + results -------------------------------------
elif state["step"] == 7:
    installed = state["installed"]
    name = installed.feature_name
    st.subheader("7 · Run first evaluation")
    st.success(f"**{name}** is activated and part of MRDS.")
    st.caption("Score it against its labeled examples to get a first result.")

    has_key = bool(get_settings().anthropic_api_key)
    if not has_key:
        st.info(
            "Set `ANTHROPIC_API_KEY` to run the evaluation here, or from a terminal run: "
            f"`mrds evaluate --feature {name}`"
        )

    back, run = st.columns(2)
    if back.button("◀ Back"):
        _goto(6)
    if run.button("Run first evaluation", type="primary", disabled=not has_key):
        with st.spinner("Evaluating…"):
            try:
                store = EvaluationStore(open_database())
                state["eval_result"] = run_first_evaluation(installed, root=".", store=store)
            except Exception as exc:  # noqa: BLE001 - surface any run failure in the UI
                st.error(f"Evaluation failed: {exc}")

    result = state.get("eval_result")
    if result is not None:
        metrics = result.aggregate_metrics
        st.success(f"Done — {metrics.total_cases} cases · pass rate {metrics.pass_rate:.0%}.")
        col1, col2, col3 = st.columns(3)
        col1.metric("Passed", metrics.passed)
        col2.metric("Failed", metrics.failed)
        col3.metric("Errored", metrics.errored)
        st.caption(
            "View full results in the dashboard → **Runs** page "
            "(`streamlit run src/mrds/dashboard/app.py`)."
        )

    st.divider()
    if st.button("Start over"):
        _reset()
