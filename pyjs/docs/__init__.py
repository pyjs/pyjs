"""Build static documentation sites with PyJS."""

from .builder import build
from .config import DocsConfig, DocsVersion, load_config

__all__ = ["DocsConfig", "DocsVersion", "build", "load_config"]
