from __future__ import annotations

import streamlit as st

from frontend.components.layout import page_header
from frontend.utils.api import APIError, SpecBridgeAPI
from frontend.utils.state import select_document


def render(api: SpecBridgeAPI) -> None:
    page_header(
        "Upload specification",
        "Start with a PDF, DOCX, TXT, Markdown, CSV, or Excel specification.",
    )
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        uploaded_file = st.file_uploader(
            "Choose a specification",
            type=["pdf", "docx", "txt", "md", "markdown", "csv", "xlsx"],
            help="The document is parsed, normalized, chunked, and stored locally.",
        )
        if uploaded_file is not None:
            st.caption(
                f"{uploaded_file.name} · {uploaded_file.size / 1024:.1f} KB"
            )
            if st.button(
                "Upload and prepare workspace",
                type="primary",
                use_container_width=True,
            ):
                try:
                    with st.spinner(
                        "Parsing structure and preparing semantic chunks..."
                    ):
                        document = api.upload(uploaded_file)
                    select_document(str(document["id"]), uploaded_file.name)
                    st.success("Specification uploaded and selected.")
                    st.code(str(document["id"]))
                    st.session_state.current_page = "Dashboard"
                except APIError as error:
                    st.error(str(error))
    with right:
        st.markdown(
            """
            <div class="content-card">
              <b>What happens after upload?</b><br><br>
              <span style="color:#94a3b8">
              1. Validate and store the source file<br>
              2. Preserve headings, sections, pages, and tables<br>
              3. Create semantic chunks<br>
              4. Store document metadata and chunks<br>
              5. Make the specification ready for intelligence agents
              </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.divider()
    st.subheader("Use an existing document")
    existing_id = st.text_input(
        "Document ID",
        placeholder="Paste a previously uploaded document UUID",
    )
    if st.button("Select document", disabled=not existing_id.strip()):
        select_document(existing_id)
        st.success("Document selected for this browser session.")
