"""Compare page: a direct A-vs-B comparison of any two runs of a feature."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_page_help
from mrds.dashboard.data import humanize_metric_name
from mrds.dashboard.help_text import SEVERITY_BADGE

st.title("Compare runs")
render_page_help("compare")

data = get_data()
feature = feature_selector(data, key="compare_feature")

if feature:
    run_ids = [r.run_uuid for r in data.runs(feature)]
    if len(run_ids) < 2:
        st.info("Need at least two runs of this feature to compare.")
    else:
        labels = data.run_label_map(feature)

        def _fmt(uuid: str) -> str:
            return labels[uuid].label if uuid in labels else uuid

        # Default to "newest (B) vs previous (A)" — the most common diff.
        col_a, col_b = st.columns(2)
        run_a = col_a.selectbox(
            "Run A (reference)", run_ids, index=1, format_func=_fmt, key="cmp_a"
        )
        run_b = col_b.selectbox("Run B (new)", run_ids, index=0, format_func=_fmt, key="cmp_b")

        if run_a == run_b:
            st.info("Pick two different runs to see a comparison.")
        else:
            comparison = data.compare_runs(run_a, run_b)
            if comparison is None:
                st.warning("Could not load one of the selected runs.")
            else:
                # What changed between the two runs — the attribution for any movement.
                prompt_note = (
                    f"**Prompt:** {comparison.baseline_prompt_version} → "
                    f"{comparison.candidate_prompt_version}"
                    f" {'*(changed)*' if comparison.prompt_changed else '*(unchanged)*'}"
                )
                dataset_note = (
                    f"**Dataset:** {comparison.baseline_dataset_version} → "
                    f"{comparison.candidate_dataset_version}"
                    f" {'*(changed)*' if comparison.dataset_changed else '*(unchanged)*'}"
                )
                st.caption(f"{prompt_note}  ·  {dataset_note}")

                # Overall verdict: regressions are drops from A to B (improvements are not).
                if comparison.severity.value == "pass":
                    st.success("🟢 No regressions from Run A to Run B.")
                else:
                    st.warning(
                        f"{SEVERITY_BADGE[comparison.severity.value]} — "
                        f"{comparison.critical_count} critical, "
                        f"{comparison.warning_count} warning metric(s) regressed from A to B."
                    )

                # Headline tiles: pass rate + each scorer's mean (all higher-is-better).
                headline = [
                    c
                    for c in comparison.comparisons
                    if c.name == "pass_rate" or c.name.endswith(".mean_score")
                ]
                if headline:
                    st.markdown("**Headline metrics** (Δ = Run B − Run A)")
                    for col, c in zip(st.columns(len(headline)), headline, strict=True):
                        if c.name == "pass_rate":
                            label, value, delta = "Pass rate", f"{c.candidate_value:.1%}", c.delta
                            col.metric(label, value, delta=f"{delta:+.1%}" if delta else None)
                        else:
                            label = c.name.split(".")[1]  # scorer.<name>.mean_score -> <name>
                            col.metric(
                                label,
                                f"{c.candidate_value:.2f}",
                                delta=f"{c.delta:+.2f}" if c.delta else None,
                            )

                st.markdown("**All metrics** — what moved, and why it matters")
                st.dataframe(
                    [
                        {
                            "metric": humanize_metric_name(c.name),
                            "Run A": round(c.baseline_value, 4),
                            "Run B": round(c.candidate_value, 4),
                            "Δ (B − A)": round(c.delta, 4),
                            "Δ%": (
                                f"{c.relative_delta:+.1%}" if c.relative_delta is not None else "—"
                            ),
                            "verdict": SEVERITY_BADGE[c.severity.value],
                            "why": c.reason,
                        }
                        for c in comparison.comparisons
                    ],
                    use_container_width=True,
                )
