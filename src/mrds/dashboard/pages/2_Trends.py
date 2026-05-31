"""Trends page: metric time-series across a feature's runs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data

st.title("Trends")
st.caption("Each point is one run, oldest to newest.")
st.info(
    "**What am I looking at?** Trends show whether the feature is improving, holding steady, "
    "or sliding over time. Each line tracks one metric across past runs."
)

with st.expander("How to read these charts"):
    st.markdown(
        "- **Pass rate** — higher is better; a downward step warns a change hurt quality.\n"
        "- **Scorer means** — per-aspect quality; one scorer dropping pinpoints *what* "
        "got worse.\n"
        "- **Latency (ms)** — time per case; lower is better. **p95** is the slow tail "
        "(95% of cases are faster than this).\n"
        "- **Token usage** — a stand-in for cost; lower is better. A jump means pricier runs."
    )

data = get_data()
feature = feature_selector(data, key="trends_feature")

if feature:
    points = data.trend(feature)
    if not points:
        st.info("No runs to chart yet.")
    else:
        frame = pd.DataFrame(
            [
                {
                    "run": p.run_uuid[:8],
                    "pass_rate": p.pass_rate,
                    "mean_latency_ms": p.mean_latency_ms,
                    "p95_latency_ms": p.p95_latency_ms,
                    "total_tokens": p.total_tokens,
                    **{f"scorer:{name}": value for name, value in p.scorer_means.items()},
                }
                for p in points
            ]
        ).set_index("run")

        st.subheader("Pass rate")
        st.line_chart(frame[["pass_rate"]])

        scorer_columns = [c for c in frame.columns if c.startswith("scorer:")]
        if scorer_columns:
            st.subheader("Scorer means")
            st.line_chart(frame[scorer_columns])

        st.subheader("Latency (ms)")
        st.line_chart(frame[["mean_latency_ms", "p95_latency_ms"]])

        st.subheader("Token usage")
        st.line_chart(frame[["total_tokens"]])
