from __future__ import annotations

import json

import streamlit as st

from frontend.components.layout import page_header
from frontend.pages.common import fetch_cached, require_document
from frontend.utils.api import APIError, SpecBridgeAPI
from frontend.utils.formatting import markdown_export, titleize


EXPORT_SOURCES = {
    "Requirements": ("requirements", "/requirements/{document_id}"),
    "Assumption Ledger": ("assumptions", "/assumptions/{document_id}"),
    "Engineering Blueprint": ("engineering", "/engineering/{document_id}"),
    "Architecture Blueprint": ("architecture", "/architecture/{document_id}"),
    "Traceability": ("traceability", "/traceability/{document_id}"),
    "Spec Health": ("health", "/spec-health/{document_id}"),
}


def render(api: SpecBridgeAPI) -> None:
    page_header(
        "Exports",
        "Take SpecBridge outputs into reviews, delivery tools, and documentation.",
    )
    document_id = require_document()
    if not document_id:
        return
    source = st.selectbox("Export source", list(EXPORT_SOURCES))
    key, path = EXPORT_SOURCES[source]
    data = fetch_cached(api, key, path.format(document_id=document_id))
    if not data:
        st.info(f"{source} has not been generated yet.")
        return
    json_bytes = json.dumps(data, indent=2).encode("utf-8")
    markdown = markdown_export(source, data).encode("utf-8")
    json_col, markdown_col, csv_col = st.columns(3)
    json_col.download_button(
        "Download JSON",
        json_bytes,
        file_name=f"{key}-{document_id}.json",
        mime="application/json",
        use_container_width=True,
    )
    markdown_col.download_button(
        "Download Markdown",
        markdown,
        file_name=f"{key}-{document_id}.md",
        mime="text/markdown",
        use_container_width=True,
        help="Frontend-generated placeholder until dedicated Markdown exports exist.",
    )
    if source == "Traceability":
        try:
            csv_bytes = api.download(f"/traceability/{document_id}/export.csv")
            csv_col.download_button(
                "Download CSV",
                csv_bytes,
                file_name=f"traceability-{document_id}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except APIError as error:
            csv_col.warning(str(error))
    else:
        csv_col.button(
            "CSV not available",
            disabled=True,
            use_container_width=True,
        )
    st.caption(
        f"Exporting {titleize(source)} for document `{document_id}`."
    )
