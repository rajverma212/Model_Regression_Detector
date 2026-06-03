"""Runs page: browse historical runs and drill into one run's results."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_case, render_page_help
from mrds.dashboard.data import filter_cases

st.title("Runs")
render_page_help("runs")

data = get_data()
feature = feature_selector(data, key="runs_feature")

if feature:
    runs = data.runs(feature)
    labels = {label.run_uuid: label for label in data.run_labels(feature)}
    st.subheader(f"{len(runs)} run(s)")
    st.dataframe(
        [
            {
                "run": labels[r.run_uuid].label if r.run_uuid in labels else r.run_uuid,
                "status": r.status,
                "triggered_by": r.triggered_by,
                "started_at": r.started_at,
                "tokens": r.total_tokens,
                "run_id": r.run_uuid,
            }
            for r in runs
        ],
        use_container_width=True,
    )

    run_ids = [r.run_uuid for r in runs]
    if run_ids:
        selected = st.selectbox(
            "Inspect run",
            run_ids,
            format_func=lambda uuid: labels[uuid].label if uuid in labels else uuid,
            key="runs_drilldown",
        )
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

            st.markdown("**Test log explorer** — browse every case and see why it passed or failed")
            cases = result.per_case_results
            segment_field = metrics.segment_field
            if not any(c.passed is False for c in cases):
                st.success("Every case passed. 🎉")

            # Filters. Outcome defaults to failures so they stay front-and-centre; an
            # empty selection on any axis means "no filter" (show all).
            fcol1, fcol2, fcol3 = st.columns(3)
            outcomes = fcol1.multiselect(
                "Outcome",
                ["passed", "failed", "errored"],
                default=["failed", "errored"],
                key="runs_outcomes",
            )
            difficulties_all = sorted({c.expected_difficulty.value for c in cases})
            difficulties = fcol2.multiselect(
                "Difficulty", difficulties_all, default=difficulties_all, key="runs_difficulty"
            )
            categories: list[str] | None = None
            if segment_field:
                categories_all = sorted(
                    {
                        str(c.expected_output[segment_field])
                        for c in cases
                        if c.expected_output.get(segment_field) is not None
                    }
                )
                categories = fcol3.multiselect(
                    segment_field.capitalize(),
                    categories_all,
                    default=categories_all,
                    key="runs_category",
                )
            search = st.text_input("Search input text or case id", key="runs_search")

            matching = filter_cases(
                cases,
                outcomes=outcomes or None,
                categories=(categories or None) if segment_field else None,
                difficulties=difficulties or None,
                search=search,
                segment_field=segment_field,
            )
            st.caption(f"Showing {len(matching)} of {len(cases)} cases.")
            if not matching:
                st.info("No cases match the current filters.")
            else:
                # render_case opens its own expander; render at top level (no nesting).
                for case in matching:
                    render_case(case, expanded=len(matching) <= 3)
