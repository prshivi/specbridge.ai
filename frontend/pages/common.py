from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from frontend.components.layout import empty_state
from frontend.utils.api import APIError, SpecBridgeAPI
from frontend.utils.state import cache_get, cache_set, selected_document_id


def require_document() -> str | None:
    document_id = selected_document_id()
    if document_id:
        return document_id
    empty_state(
        "Select a specification first",
        "Upload a document or paste an existing document ID in the sidebar.",
    )
    return None


def fetch_cached(
    api: SpecBridgeAPI,
    key: str,
    path: str,
    *,
    refresh: bool = False,
    quiet_404: bool = True,
) -> dict[str, Any] | None:
    if not refresh and (cached := cache_get(key)) is not None:
        return cached
    try:
        with st.spinner("Loading specification intelligence..."):
            return cache_set(key, api.get(path))
    except APIError as error:
        if error.status_code == 404 and quiet_404:
            return None
        st.error(str(error))
        return None


def run_action(
    label: str,
    action: Callable[[], dict[str, Any]],
    *,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    if not st.button(label, type="primary", use_container_width=True):
        return None
    try:
        with st.spinner("Running analysis and preserving traceability..."):
            result = action()
        if cache_key:
            cache_set(cache_key, result)
        st.success("Analysis completed successfully.")
        return result
    except APIError as error:
        st.error(str(error))
        return None


def generation_empty_state(label: str, endpoint_label: str) -> None:
    empty_state(
        f"{label} is not available yet",
        f"Run {endpoint_label} for the selected specification, then refresh this page.",
    )
