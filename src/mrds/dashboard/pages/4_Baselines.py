"""Baselines page: current active baseline and promotion history."""

from __future__ import annotations

import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data

st.title("Baselines")
st.caption("The trusted 'known-good' run that every new run is compared against.")
st.info(
    "**What is a baseline?** One specific run, marked as the trusted bar for quality. Exactly "
    "one baseline is active per feature, and every new run is measured against it."
)

with st.expander("Why comparisons use a baseline"):
    st.markdown(
        "- Without a fixed reference, a 6% drop looks like a normal day — a baseline gives an "
        "objective 'better or worse than what we trust?' line.\n"
        "- Baselines are promoted **deliberately** (or automatically when `main` is green), so "
        "a worse run never silently becomes the new bar.\n"
        "- **Promotion history** shows every time the bar moved, and who or what moved it."
    )

data = get_data()
feature = feature_selector(data, key="baselines_feature")

if feature:
    active = data.active_baseline(feature)
    if active is None:
        st.info("No active baseline. Promote a run with `mrds promote-baseline`.")
    else:
        run_uuid = data.run_uuid_for(active.run_id) or str(active.run_id)
        st.success(f"Active baseline: run `{run_uuid}`")
        st.caption(f"Promoted by {active.promoted_by} at {active.promoted_at}")
        if active.note:
            st.write(active.note)

    st.subheader("Promotion history")
    history = data.baseline_history(feature)
    st.dataframe(
        [
            {
                "id": b.id,
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
