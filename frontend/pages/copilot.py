from __future__ import annotations

import streamlit as st

from frontend.components.layout import page_header
from frontend.pages.common import require_document
from frontend.utils.api import APIError, SpecBridgeAPI


def render(api: SpecBridgeAPI) -> None:
    page_header(
        "Developer Copilot",
        "Ask implementation questions and receive grounded, cited answers.",
    )
    document_id = require_document()
    if not document_id:
        return
    examples = st.columns(3)
    prompts = [
        "Which API should I implement first?",
        "What validation rules apply?",
        "What happens when the integration fails?",
    ]
    for column, prompt in zip(examples, prompts, strict=True):
        if column.button(prompt, use_container_width=True):
            st.session_state.copilot_question = prompt
    question = st.text_area(
        "Developer question",
        value=st.session_state.get("copilot_question", ""),
        placeholder="Ask about a requirement, API, rule, or architecture decision...",
        height=120,
    )
    if st.button(
        "Ask SpecBridge",
        type="primary",
        disabled=not question.strip(),
    ):
        try:
            with st.spinner("Grounding the answer in approved sources..."):
                st.session_state.copilot_answer = api.post(
                    f"/copilot/{document_id}/ask",
                    {"question": question.strip()},
                )
        except APIError as error:
            st.error(str(error))
    answer = st.session_state.get("copilot_answer")
    if not answer:
        st.info("Ask a question to begin a grounded developer conversation.")
        return
    if answer.get("available"):
        st.success("Grounded answer")
        st.markdown(answer["answer"])
        st.markdown("#### Sources")
        for citation in answer.get("citations", []):
            with st.expander(f"Source chunk · {citation['source_chunk']}"):
                st.write(
                    "Requirements: "
                    + (", ".join(citation.get("requirement_ids", [])) or "None")
                )
                st.write(
                    "Architecture: "
                    + (", ".join(citation.get("architecture_ids", [])) or "None")
                )
    else:
        st.warning("Not enough information.")
        st.markdown(
            f"**Clarification needed:** {answer.get('clarification_question', '')}"
        )
