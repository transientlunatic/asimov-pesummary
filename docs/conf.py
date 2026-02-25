# Configuration file for the Sphinx documentation builder.

import sys
import os
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock dependencies that are not available at doc-build time (e.g. htcondor
# is only present on HTCondor submit nodes).
# ---------------------------------------------------------------------------
for _mod in ("htcondor", "htcondor2", "otter"):
    sys.modules.setdefault(_mod, MagicMock())

# asimov loads all registered pipeline entry-points at import time.
# asimov_pesummary is one of those entry-points, so importing it while
# asimov is mid-initialisation causes a circular-import error.  A stub
# for asimov.pipelines breaks the cycle.
_stub = MagicMock()
_stub.known_pipelines = {}
sys.modules.setdefault("asimov.pipelines", _stub)

# ---------------------------------------------------------------------------
# Project information
# ---------------------------------------------------------------------------

project = "asimov-pesummary"
copyright = "2026, Daniel Williams"
author = "Daniel Williams"

try:
    from importlib.metadata import version as _get_version
    release = _get_version("asimov-pesummary")
except Exception:
    release = "unknown"

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------

extensions = [
    "kentigern",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "numpydoc",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Autodoc
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# numpydoc
numpydoc_show_class_members = False

# Intersphinx — link into the Python stdlib
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

html_theme = "kentigern"
html_theme_options = {
    "navbar_title": "asimov-pesummary",
}
html_static_path = ["_static"]
