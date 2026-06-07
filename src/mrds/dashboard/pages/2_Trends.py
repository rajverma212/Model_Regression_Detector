"""Trends page: metric time-series across a feature's runs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_page_help

st.title("Trends")
render_page_help("trends")

data = get_data()
feature = feature_selector(data, key="trends_feature")

if feature:
    points = data.trend(feature)
    if not points:
        st.info("No runs to chart yet.")
    else:
        # Conclusion: read the latest pass-rate movement in words.
        if len(points) >= 2:
            previous, latest = points[-2].pass_rate, points[-1].pass_rate
            verb = "rose" if latest > previous else "fell" if latest < previous else "held"
            if verb == "held":
                st.markdown(f"### Pass rate held at {latest:.0%} on the latest run")
            else:
                st.markdown(
                    f"### Pass rate {verb} from {previous:.0%} to {latest:.0%} on the latest run"
                )
        else:
            st.markdown(f"### Pass rate is {points[-1].pass_rate:.0%} (first run)")

        labels = data.run_label_map(feature)
        frame = pd.DataFrame(
            [
                {
                    "run": labels[p.run_uuid].short_label
                    if p.run_uuid in labels
                    else p.run_uuid[:8],
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

        # Details: speed & cost are secondary to the quality question — tucked away.
        with st.expander("Speed & cost over time"):
            st.subheader("Latency (ms)")
            st.line_chart(frame[["mean_latency_ms", "p95_latency_ms"]])

            st.subheader("Token usage")
            st.line_chart(frame[["total_tokens"]])
