"""계약 검증. 단계 코드는 DB에 쓰기 전에 validate_contract()를 거친다.

생성된 Pydantic 모델은 if/then 규칙과 schema 밖 검사를 모른다. 모델을 직접 만들어 DB에 쓰면
계약을 건너뛰게 되므로, 모델을 만들었으면 model_dump(mode="json")으로 다시 이 함수를 거친다.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from soc.contracts.generated import (
    agent_log_schema,
    alert_schema,
    case_schema,
    event_schema,
    incident_schema,
    raw_record_schema,
    ticket_schema,
)
from soc.contracts.generated.common import asset_schema, entity_schema, verdict_schema

# 레포 루트의 contracts/. uv sync로 설치한 개발 환경 기준이며, 배포 형태가 정해지면 바꾼다.
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "contracts"

# 계약 이름 → (schema 파일, 생성 모델)
_CONTRACTS: dict[str, tuple[str, type[BaseModel]]] = {
    "raw_record": ("raw_record.schema.json", raw_record_schema.RawRecord),
    "alert": ("alert.schema.json", alert_schema.Alert),
    "event": ("event.schema.json", event_schema.Event),
    "ticket": ("ticket.schema.json", ticket_schema.Ticket),
    "incident": ("incident.schema.json", incident_schema.Incident),
    "case": ("case.schema.json", case_schema.Case),
    "agent_log": ("agent_log.schema.json", agent_log_schema.AgentLog),
    "entity": ("common/entity.schema.json", entity_schema.Entity),
    "asset": ("common/asset.schema.json", asset_schema.Asset),
    "verdict": ("common/verdict.schema.json", verdict_schema.Verdict),
}

CONTRACT_NAMES = tuple(_CONTRACTS)


@dataclass(frozen=True, order=True)
class Violation:
    """계약 위반 하나. path는 틀린 필드의 경로, rule은 어긴 규칙(JSON Schema 키워드 등)."""

    path: str
    rule: str


class ContractError(ValueError):
    """계약에 맞지 않는 데이터. 공격자가 쓴 문자열이 로그로 흘러가지 않게 입력 값은 담지 않는다."""

    def __init__(self, name: str, violations: Iterable[Violation]) -> None:
        self.name = name
        self.violations = tuple(sorted(set(violations)))
        listed = ", ".join(f"{v.path}: {v.rule}" for v in self.violations)
        super().__init__(f"{name} 계약 위반 {len(self.violations)}건 ({listed})")


def validate_contract(name: str, data: Any) -> BaseModel:
    """data가 계약 name에 맞는지 검사하고 생성된 Pydantic 모델로 돌려준다.

    순서: ① JSON Schema 검사(if/then 포함) ② schema로 쓸 수 없는 규칙 ③ Pydantic 모델로 변환.
    맞지 않으면 ContractError를 낸다.
    """
    if name not in _CONTRACTS:
        raise ValueError(f"알 수 없는 계약 이름이다. 쓸 수 있는 값: {', '.join(CONTRACT_NAMES)}")
    _, model = _CONTRACTS[name]

    violations = [v for e in _validators()[name].iter_errors(data) for v in _from_schema_error(e)]
    if not violations:
        violations = _extra_violations(name, data)
    if violations:
        raise ContractError(name, violations)

    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        # schema 검사를 통과했으면 여기 오지 않는다. 와도 입력 값이 든 원래 예외는 감춘다.
        raise ContractError(name, map(_from_pydantic_error, exc.errors())) from None


def _extra_violations(name: str, data: dict[str, Any]) -> list[Violation]:
    """JSON Schema로 쓸 수 없는 규칙. schema 검사를 통과한 data만 받는다."""
    if name == "event" and data["ocsf_class"] != data["ocsf"]["class_uid"]:
        return [Violation("ocsf.class_uid", "equals_ocsf_class")]
    return []


@cache
def _validators() -> dict[str, Draft7Validator]:
    if not SCHEMA_DIR.is_dir():
        raise RuntimeError(f"계약 schema 폴더가 없다: {SCHEMA_DIR}")
    resources = []
    for path in sorted(SCHEMA_DIR.rglob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append(
            (contents["$id"], Resource.from_contents(contents, default_specification=DRAFT7))
        )
    registry = Registry().with_resources(resources)
    return {
        name: Draft7Validator(registry.contents(schema_file), registry=registry)
        for name, (schema_file, _) in _CONTRACTS.items()
    }


def _from_schema_error(error: ValidationError) -> Iterator[Violation]:
    if error.validator in ("anyOf", "oneOf") and error.context:
        branch = _branch_matching_type(error.context)
        if branch is not None:
            for sub in branch:
                yield from _from_schema_error(sub)
            return

    path = list(error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        # 빠진 필드 이름은 schema에서 가져온다(입력 값이 아님).
        for key in error.validator_value:
            if key not in error.instance:
                yield Violation(_format_path([*path, key]), "required")
        return
    # additionalProperties는 객체 경로만 남긴다. 추가된 키 이름은 입력 값이다.
    yield Violation(_format_path(path), str(error.validator))


def _branch_matching_type(errors: Iterable[ValidationError]) -> list[ValidationError] | None:
    """ "Verdict 또는 null" 같은 선택에서 값의 타입이 맞는 갈래 하나의 오류만 고른다."""
    branches: dict[Any, list[ValidationError]] = {}
    for error in errors:
        branches.setdefault(error.relative_schema_path[0], []).append(error)
    matching = [
        branch
        for branch in branches.values()
        if not any(e.validator == "type" and not e.relative_path for e in branch)
    ]
    return matching[0] if len(matching) == 1 else None


def _from_pydantic_error(error: Any) -> Violation:
    loc = list(error["loc"])
    if error["type"] == "extra_forbidden":
        return Violation(_format_path(loc[:-1]), "additionalProperties")
    return Violation(_format_path(loc), error["type"])


def _format_path(parts: Iterable[str | int]) -> str:
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path or "(root)"
