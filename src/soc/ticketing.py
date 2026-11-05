"""Ticket 정책 설정과 PostgreSQL 활성 행(#246)."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
POLICY_KEYS = frozenset({"mode", "scenario_rule_ids"})
POLICY_MODES = frozenset({"auto", "scenario"})


class ConfigError(ValueError):
    """Ticket 정책 설정이 올바르지 않다."""


@dataclass(frozen=True)
class TicketingPolicy:
    """정규화 Alert를 Ticket으로 분기하는 현재 정책."""

    mode: str
    scenario_rule_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """API 요청·응답과 같은 JSON 모양으로 돌려준다."""
        return {"mode": self.mode, "scenario_rule_ids": list(self.scenario_rule_ids)}


def load_policy(directory: Path | None = None) -> TicketingPolicy:
    """default.toml 위에 local.toml을 덮어쓴 Ticket 정책."""
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return parse_policy(merged.get("ticketing"))


def parse_policy(value: object) -> TicketingPolicy:
    """정책 표의 키와 값 형식을 확인한다. 룰 ID는 저장된 문자열 그대로 비교한다."""
    if not isinstance(value, Mapping) or set(value) != POLICY_KEYS:
        raise ConfigError("[ticketing] 키가 올바르지 않다")
    mode = value["mode"]
    rule_ids = value["scenario_rule_ids"]
    if not isinstance(mode, str) or mode not in POLICY_MODES:
        raise ConfigError("[ticketing] mode는 auto 또는 scenario여야 한다")
    if not isinstance(rule_ids, list | tuple) or any(
        not isinstance(item, str) for item in rule_ids
    ):
        raise ConfigError("[ticketing] scenario_rule_ids는 문자열 목록이어야 한다")
    return TicketingPolicy(mode, tuple(rule_ids))


def read_active_policy(conn: psycopg.Connection) -> TicketingPolicy | None:
    """활성 DB 정책을 읽는다. 행이 없으면 None을 돌려준다."""
    row = conn.execute(
        "SELECT mode, scenario_rule_ids FROM ticketing_policy WHERE id = 1"
    ).fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        values = {"mode": row["mode"], "scenario_rule_ids": row["scenario_rule_ids"]}
    else:
        values = {"mode": row[0], "scenario_rule_ids": row[1]}
    return parse_policy(values)


def replace_active_policy(conn: psycopg.Connection, policy: TicketingPolicy) -> None:
    """활성 정책 행 하나를 삽입하거나 전체 교체한다. 호출자가 트랜잭션을 연다."""
    conn.execute(
        "INSERT INTO ticketing_policy (id, mode, scenario_rule_ids) VALUES (1, %s, %s)"
        " ON CONFLICT (id) DO UPDATE"
        " SET mode = EXCLUDED.mode, scenario_rule_ids = EXCLUDED.scenario_rule_ids",
        (policy.mode, list(policy.scenario_rule_ids)),
    )


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
