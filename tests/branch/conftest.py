"""Lets the box 25 tests reuse the in-memory stores from tests/store."""

import sys
from pathlib import Path

STORE_TESTS = str(Path(__file__).resolve().parents[1] / "store")
if STORE_TESTS not in sys.path:
    sys.path.insert(0, STORE_TESTS)
