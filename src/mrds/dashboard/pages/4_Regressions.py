"""Regressions page: inspect detected regressions for a run."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_page_help

st.title("Regressions")
render_page_help("regressions")

data = get_data()
feature = feature_selector(data, key="regressions_feature")

if feature:
    run_ids = [r.run_uuid for r in data.runs(feature)]
    if not run_ids:
        st.info("No runs recorded for this feature.")
    else:
        labels = data.run_label_map(feature)
        selected = st.selectbox(
            "Run (candidate)",
            run_ids,
            format_func=lambda uuid: labels[uuid].label if uuid in labels else uuid,
            key="regressions_run",
        )
        regressions = data.regressions_for_run(selected)
        if not regressions:
            st.success("No regressions recorded for this run.")
        else:
            st.dataframe(
                [
                    {
                        "metric": r.metric,
                        "baseline": r.baseline_value,
                        "candidate": r.candidate_value,
                        "delta": r.delta,
                        "severity": r.severity,
                        "detected_at": r.detected_at,
                    }
                    for r in regressions
                ],
                use_container_width=True,
            )
