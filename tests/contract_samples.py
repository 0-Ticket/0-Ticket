"""tests/fixtures/contracts/의 손으로 만든 계약 샘플을 읽는다.

valid/<계약 이름>.json   [{"case": 이름, "data": 샘플}]
invalid/<계약 이름>.json [{"case": 이름, "violations": [{"path", "rule"}], "data": 샘플}]
"""

import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "contracts"

CONTRACT_NAMES = (
    "raw_record",
    "ingest_checkpoint",
    "ingest_run",
    "alert",
    "event",
    "ticket",
    "incident",
    "case",
    "hunt",
    "hunt_hypotheses",
    "hunt_verification",
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


def with_depth(name: str, field: str, depth: int) -> dict[str, Any]:
    """name의 첫 올바른 샘플에서 자유 객체 field 안에 list와 dict를 번갈아 쌓는다.

    data 전체의 깊이(dict·list가 겹친 수, data 최상위 dict가 1)가 depth가 된다.
    data(1)와 field 객체(2) 아래에 가장 안쪽 빈 dict까지 depth - 2겹을 더한다.
    """
    nested: Any = {}
    for level in range(depth - 3):
        nested = [nested] if level % 2 == 0 else {"down": nested}
    data = copy.deepcopy(load("valid", name)[0]["data"])
    data[field] = {**data[field], "nested": nested}
    return data
