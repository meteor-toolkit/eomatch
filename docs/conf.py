#!/usr/bin/env python
#
# eomatch documentation build configuration file
#

from importlib.metadata import version as _pkg_version, PackageNotFoundError

# Private NPL packages and optional C-extension packages that are not
# available in the plain docs-build environment.  autodoc_mock_imports makes
# these importable as stubs during autodoc processing so Sphinx can read
# docstrings and type annotations without needing the real packages installed.
_MOCK_MODULES = [
    "processor_tools",
    "processor_tools.config",
    "processor_tools.context",
    "scrappi",
    "scrappi.product",
    "scrappi.utils",
    "scrappi.utils.plot_utils",
    "scrappi.utils.utils",
    "scrappi.fs",
    "scrappi.fs.stacfilesystem",
    "eoio",
    "orbitx",
    "cartopy",
    "cartopy.crs",
    "rasterio",
    "rasterio.crs",
    "rasterio.features",
    "rasterio.transform",
    "rasterio.warp",
    "rioxarray",
]

try:
    _version = _pkg_version("eomatch")
except PackageNotFoundError:
    _version = "0.0.0"

project_title = "eomatch".replace("_", " ").title()


# -- General configuration ---------------------------------------------

default_role = "code"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "IPython.sphinxext.ipython_directive",
    "IPython.sphinxext.ipython_console_highlighting",
    "sphinx_design",
    "myst_parser",
]

templates_path = ["_templates"]

source_suffix = [".rst", ".md"]

master_doc = "index"

project = project_title
copyright = "MetEOR Toolkit Team"
author = "MetEOR Toolkit Team"

version = _version
release = _version

language = "en"

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autodoc_mock_imports = _MOCK_MODULES

pygments_style = "sphinx"

todo_include_todos = False


# -- Options for HTML output -------------------------------------------

html_theme = "sphinx_book_theme"

html_title = "eomatch"

html_static_path = ["_static"]

htmlhelp_basename = "eomatchdoc"
# options below for sphinx_book_theme
html_theme_options = {
    "announcement": "<strong>Beta Version:</strong> This software is a beta version, results should be used with caution. Please share any feedback you have after using the tool.",
}

# -- Options for LaTeX output ------------------------------------------

latex_elements = {}

latex_documents = [
    (
        "content/user/user_guide",
        "user_manual.tex",
        "{}: User Guide".format(project_title),
        "Sam Hunt",
        "manual",
    ),
]
