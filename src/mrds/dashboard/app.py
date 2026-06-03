"""Streamlit dashboard entry point.

Run with: ``streamlit run src/mrds/dashboard/app.py``. The Runs, Trends,
Regressions, and Baselines pages appear in the sidebar (see ``pages/``).
"""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import get_data, render_page_help
from mrds.dashboard.help_text import FEATURE_INFO, HEALTH_BADGE, HEALTH_CAPTION

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
    st.metric("Features under test", len(features))
    for feature in features:
        overview = data.feature_overview(feature)
        info = FEATURE_INFO.get(feature)

        st.divider()
        st.subheader(info.title if info else overview.display_name)
        if info:
            st.write(info.summary)
            for bullet in info.bullets:
                st.markdown(f"- {bullet}")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Runs", overview.run_count)
        col2.metric(
            "Latest pass rate",
            f"{overview.latest_pass_rate:.1%}" if overview.latest_pass_rate is not None else "—",
        )
        col3.metric("Runs with regressions", overview.runs_with_regressions)
        col4.metric("Health", HEALTH_BADGE[overview.health])

        caption = HEALTH_CAPTION[overview.health]
        if overview.latest_run_label:
            caption += f" Latest: {overview.latest_run_label}."
        st.caption(caption)

    st.divider()
    st.write("Open a page from the sidebar: **Runs**, **Trends**, **Regressions**, **Baselines**.")
