"""Make shared in-memory stores, evidence fakes and the fake Elasticsearch available to L1 tests."""

import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
for folder in (TESTS / "store", TESTS / "l1" / "evidence", TESTS / "ingest"):
    path = str(folder)
    if path not in sys.path:
        sys.path.insert(0, path)
