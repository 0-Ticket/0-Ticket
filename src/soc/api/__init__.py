"""Screen API (box 27, D-027): read-only L1 results for the web screens.

``create_app(readers)`` builds the FastAPI app, ``open_readers(settings)`` opens
the read-only stores it serves from, and ``python -m soc.api`` runs it.
"""

from .app import create_app
from .readers import ApiReaders, open_readers

__all__ = ["ApiReaders", "create_app", "open_readers"]
