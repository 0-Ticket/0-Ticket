"""Command: serve the read-only L1 result API (box 27).

Usage: `uv run python -m soc.api`

The host and port come from the ``[api]`` settings; the default 127.0.0.1 keeps
the server off the network until an organization sets its own address.
"""

from collections.abc import Mapping, Sequence

import uvicorn

from soc.config import load_config

from .app import create_app
from .readers import open_reader_pool


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    settings = load_config(environ=environ)
    app = create_app(open_reader_pool(settings, environ))
    uvicorn.run(app, host=settings.api.host, port=settings.api.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
