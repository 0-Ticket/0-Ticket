"""Lets the box 14 tests reuse the MCP and queue test doubles from the sibling folders."""

import sys
from pathlib import Path

L1_TESTS = Path(__file__).resolve().parents[1]
for folder in ("mcp", "evidence"):
    path = str(L1_TESTS / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
