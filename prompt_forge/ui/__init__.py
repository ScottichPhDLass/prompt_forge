"""Web UI assets and launcher.

Run with::

    python -m prompt_forge.ui
"""
from ..ui_server import main, serve  # re-export

__all__ = ["main", "serve"]
