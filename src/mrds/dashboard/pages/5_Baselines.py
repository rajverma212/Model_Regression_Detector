"""Baselines page: current active baseline and promotion history."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_page_help

st.title("Baselines")
render_page_help("baselines")

data = get_data()
feature = feature_selector(data, key="baselines_feature")

if feature:
    labels = data.run_label_map(feature)

    def _label(run_uuid: str) -> str:
        """Readable run label, falling back to the raw uuid if it's outside the window."""
        return labels[run_uuid].label if run_uuid in labels else run_uuid

    active = data.active_baseline(feature)
    if active is None:
        st.info("No active baseline. Promote a run with `mrds promote-baseline`.")
    else:
        run_uuid = data.run_uuid_for(active.run_id) or str(active.run_id)
        # Conclusion: name the bar *and* its height (reuses the existing pass-rate read).
        pass_rate = data.baseline_pass_rate(feature)
        headline = f"Active baseline: {_label(run_uuid)}"
        if pass_rate is not None:
            headline += f" — {pass_rate:.0%} pass rate"
        st.success(headline)
        st.caption(f"Promoted by {active.promoted_by} at {active.promoted_at}")
        if active.note:
            st.write(active.note)

    # Details: the promotion audit trail, folded away.
    history = data.baseline_history(feature)
    with st.expander("Promotion history"):
        st.dataframe(
            [
                {
                    "id": b.id,
                    "run": _label(data.run_uuid_for(b.run_id) or str(b.run_id)),
                    "run_uuid": data.run_uuid_for(b.run_id) or str(b.run_id),
                    "active": bool(b.is_active),
                    "promoted_by": b.promoted_by,
                    "promoted_at": b.promoted_at,
                    "note": b.note,
                }
                for b in history
            ],
            use_container_width=True,
        )
