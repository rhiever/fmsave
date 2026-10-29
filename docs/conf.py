"""Sphinx configuration for fmsave documentation."""

import shutil
from pathlib import Path

from sphinx.application import Sphinx

from fmsave import __version__

project = "fmsave"
author = "Randy Olson"
copyright = "2026, Randy Olson"
version = __version__
release = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

source_suffix = {
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]

nitpicky = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pandas": ("https://pandas.pydata.org/docs", None),
}

autodoc_member_order = "bysource"
autodoc_typehints = "description"

templates_path = ["_templates"]
exclude_patterns = ["_build", "app", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path = ["_static"]
html_title = f"fmsave {version}"


def copy_web_app(app: Sphinx, exception: BaseException | None) -> None:
    """Copy the web app in docs/app to /app/ in the built site, as it is."""
    if exception is None and app.builder.format == "html":
        source = Path(__file__).parent / "app"
        shutil.copytree(
            source,
            Path(app.outdir) / "app",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )


def setup(app: Sphinx) -> None:
    app.connect("build-finished", copy_web_app)
