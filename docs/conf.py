"""Build API documentation from source without importing the RPC runtime."""

from pathlib import Path

project = "dank_mids"
copyright = "2024, BobTheBuidler"
author = "BobTheBuidler"
extensions = ["autoapi.extension", "sphinx.ext.napoleon", "sphinx.ext.intersphinx"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_theme = "sphinx_rtd_theme"
autoapi_type = "python"
autoapi_dirs = [str(Path(__file__).resolve().parents[1] / "dank_mids")]
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
    "imported-members",
]
autoapi_ignore = ["*/_vendor/*", "*/interfaces/*"]
autoapi_keep_files = False
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "web3": ("https://web3py.readthedocs.io/en/stable/", None),
}
