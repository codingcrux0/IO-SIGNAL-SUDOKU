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
index_path = os.path.join(build_dir, "index.html")

if not os.path.isfile(index_path):
    st.error(f"Frontend build is missing: {index_path}")
    st.stop()

with open(index_path, "r", encoding="utf-8") as file:
    html = file.read()

# Inline the generated JS and CSS, so Streamlit does not need to serve Vite asset URLs.
import re
from urllib.parse import quote

asset_pattern = re.compile(r'(src|href)="([^"]+)"')

def inline_asset(match):
    attr, asset_url = match.groups()
    if asset_url.startswith(("http://", "https://", "data:", "#")):
        return match.group(0)
    asset_path = os.path.join(build_dir, asset_url.removeprefix("./").lstrip("/"))
    if not os.path.isfile(asset_path):
        return match.group(0)
    with open(asset_path, "rb") as asset_file:
        asset = asset_file.read()
    if asset_path.endswith(".js"):
        content = asset.decode("utf-8")
        return "<script type=\"module\">" + content + "</script>"
    if asset_path.endswith(".css"):
        content = asset.decode("utf-8")
        return "<style>" + content + "</style>"
    return match.group(0)

html = asset_pattern.sub(inline_asset, html)
components.html(html, height=6000, scrolling=True)
