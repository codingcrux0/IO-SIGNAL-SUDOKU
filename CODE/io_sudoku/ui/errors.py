"""Error boundary: one broken view must never take the whole app down."""
from __future__ import annotations

import hashlib
import traceback
from contextlib import contextmanager
from typing import Iterator

import streamlit as st


@contextmanager
def error_boundary(name: str) -> Iterator[None]:
    """Run a view; on any exception show a friendly message and a diagnostics id, never re-raise."""
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - this is the safety net
        trace = traceback.format_exc()
        diag_id = hashlib.sha256(trace.encode("utf-8")).hexdigest()[:8]
        st.error(f"{name} could not be displayed. Try “Re-solve” or reload the page. "
                 f"If it keeps happening, send the Support Bundle with diagnostics id {diag_id}.")
        with st.expander("Diagnostics"):
            st.code(f"{diag_id}  {type(exc).__name__}\n\n{trace}", language="text")
