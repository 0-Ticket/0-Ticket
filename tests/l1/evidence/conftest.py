"""Lets the queue tests reuse the MCP and specialist test doubles from the sibling folders."""

import sys
from pathlib import Path

L1_TESTS = Path(__file__).resolve().parents[1]
for folder in ("mcp", "specialists"):
    path = str(L1_TESTS / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
