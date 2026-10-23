import streamlit as st
import streamlit.components.v1 as components
import os

# Set page config
st.set_page_config(layout="wide")

# The path to your built React files
build_path = os.path.join(os.path.dirname(__file__), "frontend_build")

# Declare the component
# This looks for index.html inside the build_path
figma_app = components.declare_component("io_sudoku_figma_app", path=build_path)

# Render the component
figma_app()
