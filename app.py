import os
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="IO Signal Sudoku",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    #MainMenu, header, footer, [data-testid="stToolbar"],
    [data-testid="stHeader"], [data-testid="stDecoration"],
    [data-testid="stSidebar"], .stDeployButton { display: none !important; }
    html, body, [data-testid="stAppViewContainer"],
    [data-testid="stMain"], .main, .block-container {
        padding: 0 !important;
        margin: 0 !important;
        max-width: 100% !important;
        background: #080d17 !important;
    }
    iframe { border: 0 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

build_dir = os.path.join(os.path.dirname(__file__), "frontend_build")
if not os.path.isfile(os.path.join(build_dir, "index.html")):
    st.error("The Figma frontend build is missing. Build the frontend and include CODE/io_sudoku_app/frontend_build in the repository.")
else:
    figma_app = components.declare_component("io_sudoku_figma_app", path=build_dir)
    figma_app(key="io_sudoku_figma_app")
