from __future__ import annotations

import html

import streamlit as st

from frontend.components.layout import empty_state, page_header
from frontend.pages.common import fetch_cached, require_document
from frontend.utils.api import APIError, SpecBridgeAPI


def _summaries(items: list[dict]) -> str:
    return ", ".join(item.get("summary", item.get("artifact_id", "")) for item in items)


def render(api: SpecBridgeAPI) -> None:
    page_header(
        "Traceability",
        "Follow every business requirement through engineering delivery and source evidence.",
    )
    document_id = require_document()
    if not document_id:
        return
    data = fetch_cached(api, "traceability", f"/traceability/{document_id}")
    if not data:
        empty_state(
            "Traceability is not ready",
            "Generate requirements and downstream blueprints first.",
        )
        return
    columns = st.columns(3)
    columns[0].metric("Requirements", data.get("total_requirements", 0))
    columns[1].metric("At risk", data.get("requirements_with_risks", 0))
    columns[2].metric(
        "Need clarification",
        data.get("requirements_needing_clarification", 0),
    )
    query = st.text_input("Filter requirements", placeholder="ID or keyword")
    rows = [
        row
        for row in data.get("rows", [])
        if not query
        or query.casefold()
        in (row["requirement_id"] + " " + row["business_requirement"]).casefold()
    ]
    for row in rows:
        with st.expander(
            f"{row['requirement_id']} · {row['business_requirement'][:90]}"
        ):
            nodes = [
                ("Business Requirement", row["requirement_id"]),
                ("User Story", _summaries(row.get("user_stories", [])) or "—"),
                ("API", _summaries(row.get("apis", [])) or "—"),
                (
                    "DB Entity",
                    _summaries(row.get("database_entities", [])) or "—",
                ),
                (
                    "Backend Task",
                    _summaries(row.get("backend_tasks", [])) or "—",
                ),
                (
                    "Assumption / Risk",
                    ", ".join(
                        [
                            *(item["assumption_id"] for item in row.get("assumptions", [])),
                            *(item["risk_id"] for item in row.get("risks", [])),
                        ]
                    )
                    or "—",
                ),
                (
                    "Source Section",
                    row.get("source_section", {}).get("section") or "—",
                ),
            ]
            chain = "<div class='trace-chain'>" + "".join(
                (
                    f"<span class='trace-node'><b>{html.escape(label)}</b><br>"
                    f"{html.escape(value[:80])}</span>"
                    + (
                        "<span class='trace-arrow'>→</span>"
                        if index < len(nodes) - 1
                        else ""
                    )
                )
                for index, (label, value) in enumerate(nodes)
            ) + "</div>"
            st.markdown(chain, unsafe_allow_html=True)
            if row.get("risks"):
                st.markdown("**Risks**")
                for risk in row["risks"]:
                    st.warning(f"{risk['severity'].upper()} · {risk['description']}")
            if row.get("clarifications"):
                st.markdown("**Clarifications**")
                for clarification in row["clarifications"]:
                    st.info(clarification["question"])
    try:
        csv_bytes = api.download(f"/traceability/{document_id}/export.csv")
        st.download_button(
            "Download traceability CSV",
            csv_bytes,
            file_name=f"specbridge-traceability-{document_id}.csv",
            mime="text/csv",
        )
    except APIError:
        st.caption("CSV export is currently unavailable.")
