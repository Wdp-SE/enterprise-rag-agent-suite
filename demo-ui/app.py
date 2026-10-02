"""Single active Streamlit entry point for the public edge-AI workbench."""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="研发知识版本服务与变更影响审查",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

from public_workbench import render

render()
