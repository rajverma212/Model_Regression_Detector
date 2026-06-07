"""Dataset page: browse the hand-labeled golden dataset a feature is tested against."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from mrds.dashboard._shared import feature_selector, get_data, render_page_help

st.title("Dataset")
render_page_help("dataset")

data = get_data()
feature = feature_selector(data, key="dataset_feature")

if feature:
    view = data.dataset_view(feature)
    if view is None:
        st.info("No dataset file found on disk for this feature.")
    else:
        segment_field = data.segment_field_for(feature)

        st.subheader(f"{view.feature} · {view.version}")
        st.write(view.description)

        difficulties_all = sorted({c.difficulty for c in view.cases if c.difficulty})
        categories_all = (
            sorted(
                {
                    str(c.expected[segment_field])
                    for c in view.cases
                    if segment_field and c.expected.get(segment_field) is not None
                }
            )
            if segment_field
            else []
        )

        # Conclusion: one-line coverage takeaway, from the counts already shown.
        coverage_bits = []
        if segment_field and categories_all:
            coverage_bits.append(f"{len(categories_all)} categories")
        if difficulties_all:
            coverage_bits.append(f"{len(difficulties_all)} difficulty levels")
        summary = f"**{view.case_count} hand-labeled cases**"
        if coverage_bits:
            summary += " across " + " and ".join(coverage_bits)
        st.markdown(summary + ".")

        col1, col2, col3 = st.columns(3)
        col1.metric("Cases", view.case_count)
        col2.metric("Difficulty levels", len(difficulties_all))
        if segment_field:
            col3.metric(segment_field.capitalize() + " values", len(categories_all))

        # Details: distribution charts, tucked away so the case browser sits closer.
        with st.expander("Coverage breakdown"):
            dist_cols = st.columns(2 if segment_field else 1)
            difficulty_counts = pd.Series(
                [c.difficulty for c in view.cases if c.difficulty]
            ).value_counts()
            dist_cols[0].caption("By difficulty")
            dist_cols[0].bar_chart(difficulty_counts)
            if segment_field:
                category_counts = pd.Series(
                    [
                        str(c.expected[segment_field])
                        for c in view.cases
                        if c.expected.get(segment_field) is not None
                    ]
                ).value_counts()
                dist_cols[1].caption(f"By {segment_field}")
                dist_cols[1].bar_chart(category_counts)

        # Filters + browsable case list.
        st.markdown("**Cases**")
        fcol1, fcol2 = st.columns(2)
        difficulties = fcol1.multiselect(
            "Difficulty", difficulties_all, default=difficulties_all, key="dataset_difficulty"
        )
        categories = (
            fcol2.multiselect(
                segment_field.capitalize(),
                categories_all,
                default=categories_all,
                key="dataset_cat",
            )
            if segment_field
            else None
        )
        search = st.text_input("Search input text or case id", key="dataset_search")

        needle = search.strip().lower()
        rows = []
        for case in view.cases:
            if difficulties and case.difficulty not in difficulties:
                continue
            if (
                segment_field
                and categories is not None
                and str(case.expected.get(segment_field)) not in categories
            ):
                continue
            if needle and needle not in (case.case_id + " " + case.input_text).lower():
                continue
            row = {
                "case": case.case_id,
                "input": case.input_text or str(case.input),
                "difficulty": case.difficulty,
                "notes": case.notes,
            }
            if segment_field:
                row[segment_field] = str(case.expected.get(segment_field, ""))
            rows.append(row)

        st.caption(f"Showing {len(rows)} of {view.case_count} cases.")
        st.dataframe(rows, use_container_width=True)
