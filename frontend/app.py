import os

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(page_title="SpecBridge AI", page_icon="🌉", layout="wide")

st.title("SpecBridge AI")
st.subheader("Specification intelligence for engineering-ready requirements")
st.info(
    "This initial scaffold is ready. Requirement ingestion and AI workflows "
    "will be introduced in later milestones."
)

if st.button("Check API health", type="primary"):
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        response.raise_for_status()
        st.success(f"Backend status: {response.json()['status']}")
    except (requests.RequestException, KeyError, ValueError) as error:
        st.error(f"Unable to reach the backend: {error}")

