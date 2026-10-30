"""Screen API (L1 result read, unnumbered, D-027): read-only L1 results for the web screens.

``create_app(reader_pool)`` builds the FastAPI app, ``open_reader_pool(settings)``
makes the pool of read-only connections it borrows one of per request, and
``python -m soc.api`` runs it.
"""

from .app import create_app
from .readers import ApiReaderPool, ApiReaders, open_reader_pool

__all__ = ["ApiReaderPool", "ApiReaders", "create_app", "open_reader_pool"]
