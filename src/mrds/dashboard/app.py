"""Streamlit dashboard entry point.

Run with: ``streamlit run src/mrds/dashboard/app.py``. The Runs, Trends,
Regressions, and Baselines pages appear in the sidebar (see ``pages/``).
"""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import get_data, render_page_help
from mrds.dashboard.help_text import FEATURE_INFO, HEALTH_BADGE, HEALTH_CAPTION, KPI_HELP

st.set_page_config(page_title="MRDS Dashboard", layout="wide")
st.title("Model Regression Detection System")
st.caption("Read-only view of evaluation history, trends, regressions, and baselines.")

st.info(
    "**A safety net for AI features.** Just as unit tests and CI stop broken code from "
    "shipping, MRDS runs an AI feature against a fixed set of hand-labeled examples, scores "
    "the results, and compares each new run against a trusted 'known-good' run (the "
    "*baseline*). If quality drops too far, deployments are blocked."
)

# Detailed reference lives in the sidebar so it stays visible while scrolling.
render_page_help("home")

data = get_data()
features = data.features()

if not features:
    st.info("No runs recorded yet. Use the CLI: `mrds evaluate --feature <name>`.")
else:
    # Demoted from a headline tile to a small caption — a count, not an answer.
    st.caption(f"{len(features)} feature(s) under test.")
    for feature in features:
        overview = data.feature_overview(feature)
        info = FEATURE_INFO.get(feature)
        title = info.title if info else overview.display_name

        st.divider()
        # Conclusion: feature name + health verdict, with its caption directly under it.
        st.subheader(f"{title} — {HEALTH_BADGE[overview.health]}")
        caption = HEALTH_CAPTION[overview.health]
        if overview.latest_run_label:
            caption += f" Latest: {overview.latest_run_label}."
        st.caption(caption)
        if info:
            st.write(info.summary)

        # Evidence: verdict-first tile row.
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Health", HEALTH_BADGE[overview.health], help=KPI_HELP["health"])
        col2.metric(
            "Latest pass rate",
            f"{overview.latest_pass_rate:.1%}" if overview.latest_pass_rate is not None else "—",
            help=KPI_HELP["latest_pass_rate"],
        )
        col3.metric(
            "Runs with regressions",
            overview.runs_with_regressions,
            help=KPI_HELP["runs_with_regressions"],
        )
        col4.metric("Runs", overview.run_count, help=KPI_HELP["runs"])

        # Details: what the feature classifies.
        if info and info.bullets:
            with st.expander("What it classifies"):
                for bullet in info.bullets:
                    st.markdown(f"- {bullet}")

    st.divider()
    st.write("Open a page from the sidebar: **Runs**, **Trends**, **Regressions**, **Baselines**.")

# Cross-link into the create-a-feature surface (the Next.js "Evaluation OS" web app).
st.divider()
st.caption(
    "➕ **Onboard a new feature** — use the web app's *Create feature* flow "
    "(`web/app/create` → `POST /api/onboarding/activate`)."
)
