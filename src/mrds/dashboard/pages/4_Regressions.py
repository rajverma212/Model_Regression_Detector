"""Regressions page: explain detected regressions and drill to their root-cause cases."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_case, render_page_help
from mrds.dashboard.data import cases_for_metric, humanize_metric_name
from mrds.dashboard.help_text import SEVERITY_BADGE

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
        records = data.regressions_for_run(selected)
        if not records:
            st.success("No regressions recorded for this run. ✅")
        else:
            # Recompute the comparison against the baseline this run was measured against,
            # to recover the plain-English reasons (not persisted) and the failing cases.
            baseline_uuid = data.run_uuid_for(records[0].baseline_run_id)
            comparison = data.compare_runs(baseline_uuid, selected) if baseline_uuid else None

            # Impact banner.
            if comparison is not None and comparison.is_blocking:
                st.error(
                    "🔴 **Critical regression** — in CI this would **block the deploy**, "
                    "exactly like a failing test."
                )
            else:
                st.warning(
                    "🟡 **Regression detected** — a noticeable dip worth reviewing "
                    "(not release-blocking)."
                )

            # Conclusion: one-line summary of how many regressed and the worst offender.
            if comparison is not None and comparison.regressions:
                worst = max(
                    comparison.regressions,
                    key=lambda c: (c.severity.value == "critical", abs(c.relative_delta or 0.0)),
                )
                worst_delta = (
                    f"{worst.relative_delta:+.1%}"
                    if worst.relative_delta is not None
                    else f"{worst.delta:+.4g}"
                )
                st.caption(
                    f"{len(comparison.regressions)} metric(s) regressed; "
                    f"worst: {humanize_metric_name(worst.name)} ({worst_delta})."
                )

            if baseline_uuid:
                baseline_label = (
                    labels[baseline_uuid].label if baseline_uuid in labels else baseline_uuid
                )
                st.caption(f"Compared against baseline: {baseline_label}")

            # Prefer the recomputed comparison (it carries reasons + relative deltas);
            # fall back to the persisted records if the baseline can't be reconstructed.
            regressed = comparison.regressions if comparison is not None else []
            if regressed:
                # Evidence: the full regressed-metrics table, folded so the root-cause
                # drill below stays prominent.
                with st.expander(f"All regressed metrics ({len(regressed)}) — and why"):
                    st.dataframe(
                        [
                            {
                                "metric": humanize_metric_name(mc.name),
                                "baseline": round(mc.baseline_value, 4),
                                "candidate": round(mc.candidate_value, 4),
                                "Δ": round(mc.delta, 4),
                                "Δ%": (
                                    f"{mc.relative_delta:+.1%}"
                                    if mc.relative_delta is not None
                                    else "—"
                                ),
                                "severity": SEVERITY_BADGE[mc.severity.value],
                                "why": mc.reason,
                            }
                            for mc in regressed
                        ],
                        use_container_width=True,
                    )
            else:
                st.dataframe(
                    [
                        {
                            "metric": humanize_metric_name(r.metric),
                            "baseline": r.baseline_value,
                            "candidate": r.candidate_value,
                            "delta": r.delta,
                            "severity": r.severity,
                        }
                        for r in records
                    ],
                    use_container_width=True,
                )

            # Root cause: pick a regressed metric and see the exact cases behind it.
            if regressed:
                st.markdown("**Root cause — the cases behind a regressed metric**")
                metric_names = [mc.name for mc in regressed]
                chosen = st.selectbox(
                    "Regressed metric",
                    metric_names,
                    format_func=humanize_metric_name,
                    key="regressions_metric",
                )
                chosen_mc = next(mc for mc in regressed if mc.name == chosen)
                st.caption(f"Why it regressed: {chosen_mc.reason}")

                candidate_result = data.run_detail(selected)
                if candidate_result is not None:
                    contributing = cases_for_metric(
                        chosen,
                        candidate_result.per_case_results,
                        segment_field=candidate_result.aggregate_metrics.segment_field,
                    )
                    if not contributing:
                        st.info(
                            "This is an aggregate metric (e.g. latency or tokens) — there are "
                            "no specific failing cases to show."
                        )
                    else:
                        st.caption(f"{len(contributing)} case(s) dragged this metric down:")
                        for case in contributing:
                            render_case(case, expanded=len(contributing) <= 3)
