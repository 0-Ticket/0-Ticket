"""tests/fixtures/contracts/의 손으로 만든 계약 샘플을 읽는다.

valid/<계약 이름>.json   [{"case": 이름, "data": 샘플}]
invalid/<계약 이름>.json [{"case": 이름, "violations": [{"path", "rule"}], "data": 샘플}]
"""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "contracts"

CONTRACT_NAMES = (
    "raw_record",
    "alert",
    "event",
    "ticket",
    "incident",
    "case",
    "agent_log",
    "entity",
    "asset",
    "verdict",
)


def load(kind: str, name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / kind / f"{name}.json").read_text(encoding="utf-8"))


def cases(kind: str) -> list[tuple[str, dict[str, Any]]]:
    """(계약 이름, 샘플) 목록."""
    return [(name, case) for name in CONTRACT_NAMES for case in load(kind, name)]


def case_ids(items: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [f"{name}-{case['case']}" for name, case in items]


def load_schema(relative_path: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / relative_path).read_text(encoding="utf-8"))
