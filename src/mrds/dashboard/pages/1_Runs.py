"""Runs page: browse historical runs and drill into one run's results."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data

st.title("Runs")
st.caption("Each row is one evaluation of the feature — open one to see how it scored.")
st.info(
    "**What am I looking at?** A *run* is a single test of the AI feature against a fixed set "
    "of hand-labeled examples. Pick a run to see its overall scores and every individual result."
)

with st.expander("What do these numbers mean?"):
    st.markdown(
        "- **Pass rate** — share of cases the feature got *completely* right. 90%+ is strong; "
        "a sudden drop is the thing to worry about.\n"
        "- **Passed / Failed / Errored** — fully correct · wrong on a check · crashed "
        "(e.g. the model returned invalid output).\n"
        "- **Scorer mean_score** — each scorer grades one aspect (`category_match` = right "
        "category, `summary_quality` = sensible summary). 1.0 = perfect across all cases.\n"
        "- **Segment metrics** — the same scores split by group (here, email category), so you "
        "can see which categories are strong or weak.\n"
        "- **Per-case results** — raw detail per example: pass/fail, **latency** (time), and "
        "**tokens** (a proxy for cost)."
    )

data = get_data()
feature = feature_selector(data, key="runs_feature")

if feature:
    runs = data.runs(feature)
    st.subheader(f"{len(runs)} run(s)")
    st.dataframe(
        [
            {
                "run_id": r.run_uuid,
                "status": r.status,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at,
                "tokens": r.total_tokens,
            }
            for r in runs
        ],
        use_container_width=True,
    )

    run_ids = [r.run_uuid for r in runs]
    if run_ids:
        selected = st.selectbox("Inspect run", run_ids, key="runs_drilldown")
        result = data.run_detail(selected)
        if result is not None:
            metrics = result.aggregate_metrics
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Pass rate", f"{metrics.pass_rate:.1%}")
            col2.metric("Passed", metrics.passed)
            col3.metric("Failed", metrics.failed)
            col4.metric("Errored", metrics.errored)
            st.caption(
                f"prompt {result.prompt_version} · dataset {result.dataset_version} "
                f"· model {result.model} · {result.duration_seconds:.2f}s"
            )

            st.markdown("**Scorer metrics**")
            st.dataframe(
                [
                    {"scorer": s.name, "mean_score": s.mean_score, "pass_rate": s.pass_rate}
                    for s in metrics.scorers.values()
                ],
                use_container_width=True,
            )

            if metrics.segments:
                st.markdown(f"**Segment metrics (by {metrics.segment_field})**")
                st.dataframe(
                    [
                        {"segment": s.segment, "count": s.count, "pass_rate": s.pass_rate}
                        for s in metrics.segments.values()
                    ],
                    use_container_width=True,
                )

            st.markdown("**Per-case results**")
            st.dataframe(
                [
                    {
                        "case": c.case_id,
                        "difficulty": c.expected_difficulty.value,
                        "passed": c.passed,
                        "latency_ms": c.latency_ms,
                        "tokens": c.total_tokens,
                        "error": c.error or "",
                    }
                    for c in result.per_case_results
                ],
                use_container_width=True,
            )
