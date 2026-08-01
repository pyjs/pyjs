"""Build static documentation sites with PyJS."""

from .builder import build
from .config import DocsConfig, load_config

__all__ = ["DocsConfig", "build", "load_config"]
