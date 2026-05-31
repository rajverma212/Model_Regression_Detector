"""Regressions page: inspect detected regressions for a run."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data

st.title("Regressions")
st.caption("Where a run scored worse than the trusted baseline.")
st.info(
    "**What is a regression?** When a new run scores measurably worse than the baseline, "
    "MRDS flags each metric that moved the wrong way and rates how serious it is."
)

with st.expander("Severity, and why deployments get blocked"):
    st.markdown(
        "- 🟡 **WARNING** — a noticeable dip worth reviewing, but not release-blocking.\n"
        "- 🔴 **CRITICAL** — a drop big enough that shipping is risky. In CI this fails the "
        "build and **blocks the merge**, exactly like a failing test.\n"
        "- **delta** — how much the metric changed vs the baseline; the detector has already "
        "decided this move is bad.\n"
        "- **No regressions** = the run held up against the baseline. That's the good outcome."
    )

data = get_data()
feature = feature_selector(data, key="regressions_feature")

if feature:
    run_ids = [r.run_uuid for r in data.runs(feature)]
    if not run_ids:
        st.info("No runs recorded for this feature.")
    else:
        selected = st.selectbox("Run (candidate)", run_ids, key="regressions_run")
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
