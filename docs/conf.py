"""Sphinx configuration for fmsave documentation."""

import hashlib
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


WEB_APP_ENTRY_POINTS = ("theme.js", "app.css", "app.js")


def copy_web_app(app: Sphinx, exception: BaseException | None) -> None:
    """Copy the web app in docs/app to /app/ in the built site.

    The page's own files are requested with ?v= and a hash of the app's contents, which
    app.js passes on to everything it loads, so a browser never mixes files from two deploys.
    """
    if exception is not None or app.builder.format != "html":
        return
    source = Path(__file__).parent / "app"
    target = Path(app.outdir) / "app"
    shutil.copytree(
        source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
    )
    digest = hashlib.sha256()
    for path in sorted(source.glob("*")):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    version = digest.hexdigest()[:12]
    page = target / "index.html"
    html = page.read_text(encoding="utf-8")
    for name in WEB_APP_ENTRY_POINTS:
        html = html.replace(f'"{name}"', f'"{name}?v={version}"')
    page.write_text(html, encoding="utf-8")


def setup(app: Sphinx) -> None:
    app.connect("build-finished", copy_web_app)
