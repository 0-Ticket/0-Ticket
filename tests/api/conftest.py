"""Lets the L1 result API tests reuse the store and queue test doubles from the other folders."""

import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
for folder in ("store", "l1", "l1/evidence"):
    path = str(TESTS / folder)
    if path not in sys.path:
        sys.path.insert(0, path)
