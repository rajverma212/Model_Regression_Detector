"""Streamlit dashboard entry point.

Run with: ``streamlit run src/mrds/dashboard/app.py``. The Runs, Trends,
Regressions, and Baselines pages appear in the sidebar (see ``pages/``).
"""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import get_data

st.set_page_config(page_title="MRDS Dashboard", layout="wide")
st.title("Model Regression Detection System")
st.caption("Read-only view of evaluation history, trends, regressions, and baselines.")

st.info(
    "**A safety net for AI features.** Just as unit tests and CI stop broken code from "
    "shipping, MRDS runs an AI feature against a fixed set of hand-labeled examples, scores "
    "the results, and compares each new run against a trusted 'known-good' run (the "
    "*baseline*). If quality drops too far, deployments are blocked."
)

with st.expander("What am I looking at? — the four pages"):
    st.markdown(
        "- **Runs** — every evaluation of the feature, with its scores. Inspect one run here.\n"
        "- **Trends** — how scores, speed, and cost move across runs over time.\n"
        "- **Regressions** — where a run got worse than the baseline, and how serious it is.\n"
        "- **Baselines** — which run is the current 'known-good' bar everything compares to."
    )

with st.expander("Key terms, in plain English"):
    st.markdown(
        "- **Run** — one evaluation of the feature against the test set.\n"
        "- **Pass rate** — share of test cases the feature got fully right. Higher is better.\n"
        "- **Baseline** — the trusted 'known-good' run that new runs are measured against.\n"
        "- **Regression** — a new run doing measurably worse than the baseline.\n"
        "- **Severity** — WARNING (worth a look) vs CRITICAL (bad enough to block a release)."
    )

data = get_data()
features = data.features()

if not features:
    st.info("No runs recorded yet. Use the CLI: `mrds evaluate --feature <name>`.")
else:
    st.metric("Features under test", len(features))
    for feature in features:
        st.write(f"- **{feature}** — {len(data.runs(feature))} run(s)")
    st.write("Open a page from the sidebar: **Runs**, **Trends**, **Regressions**, **Baselines**.")
