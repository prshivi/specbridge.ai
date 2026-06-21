from __future__ import annotations

import html
from typing import Any

import streamlit as st

from frontend.utils.formatting import pretty_json, severity, titleize


def product_header() -> None:
    st.markdown(
        """
        <section class="product-hero">
          <span class="hero-kicker">Specification intelligence workspace</span>
          <h1>SpecBridge AI</h1>
          <p><b>From Business Intent to Engineering Execution.</b><br>
          Turn fragmented specifications into reviewable requirements, engineering
          blueprints, architecture decisions, and grounded developer answers.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, description: str) -> None:
    st.markdown(
        f"<div class='page-title'>{html.escape(title)}</div>"
        f"<div class='page-copy'>{html.escape(description)}</div>",
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: int | float | str,
    icon: str,
    *,
    note: str = "",
) -> None:
    st.markdown(
        f"""
        <div class="metric-tile">
          <div class="metric-icon">{icon}</div>
          <div class="metric-number">{html.escape(str(value))}</div>
          <div class="metric-name">{html.escape(label)}</div>
          <div class="metric-note">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def severity_badge(value: str | None) -> str:
    normalized = severity(value)
    return (
        f"<span class='severity {normalized}'>"
        f"{html.escape(titleize(normalized))}</span>"
    )


def empty_state(title: str, copy: str) -> None:
    st.markdown(
        f"<div class='empty-state'><b>{html.escape(title)}</b><br>"
        f"{html.escape(copy)}</div>",
        unsafe_allow_html=True,
    )


def json_expander(label: str, payload: Any) -> None:
    with st.expander(label):
        st.code(pretty_json(payload), language="json")


def source_chips(chunk_ids: list[str], sections: list[str] | None = None) -> None:
    chunks = ", ".join(chunk_ids) or "No chunks"
    st.caption(f"Source chunks: {chunks}")
    if sections:
        st.caption(f"Source sections: {', '.join(sections)}")
