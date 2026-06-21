from __future__ import annotations

from typing import Any

import streamlit as st


DEFAULT_STATE: dict[str, Any] = {
    "selected_document_id": "",
    "selected_document_name": "",
    "workspace_cache": {},
    "current_page": "Upload",
}


def initialize_state() -> None:
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, dict) else value


def select_document(document_id: str, name: str = "") -> None:
    st.session_state.selected_document_id = document_id.strip()
    st.session_state.selected_document_name = name
    st.session_state.workspace_cache = {}


def selected_document_id() -> str:
    return str(st.session_state.get("selected_document_id", "")).strip()


def cache_get(key: str) -> Any | None:
    return st.session_state.workspace_cache.get(key)


def cache_set(key: str, value: Any) -> Any:
    st.session_state.workspace_cache[key] = value
    return value


def cache_clear() -> None:
    st.session_state.workspace_cache = {}
