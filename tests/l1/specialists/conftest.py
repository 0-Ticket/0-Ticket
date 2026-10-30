"""Lets the specialist tests reuse the MCP, queue and L1 input test doubles from the L1 folders."""

import sys
from pathlib import Path

L1_TESTS = Path(__file__).resolve().parents[1]
for path in (str(L1_TESTS / "mcp"), str(L1_TESTS / "evidence"), str(L1_TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
