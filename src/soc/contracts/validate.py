"""계약 검증. 단계 코드는 DB에 쓰기 전에 validate_contract()를 거친다.

생성된 Pydantic 모델은 if/then 규칙과 schema 밖 검사를 모른다. 모델을 직접 만들어 DB에 쓰면
계약을 건너뛰게 되므로, 모델을 만들었으면 model_dump(mode="json")으로 다시 이 함수를 거친다.

목표: 이 함수를 통과한 값은 값 때문에 PostgreSQL INSERT가 실패하지 않는다(외래 키·유일 제약은 별개).
그래서 JSON으로 나타낼 수 없는 값, NaN·Infinity, NUL 문자(U+0000), 문자열이 아닌 dict 키를
(root): json으로 거부한다. 짝 없는 서로게이트(U+D800~U+DFFF)는 아직 막지 않는다.
"""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, validators
from jsonschema.exceptions import ValidationError
from jsonschema.protocols import Validator
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

    순서: ① JSON 사전 검사(JSON 값인지, NaN·Infinity, NUL, 문자열이 아닌 키) ② JSON Schema 검사
    (if/then 포함) ③ schema로 쓸 수 없는 규칙 ④ Pydantic 모델로 변환.
    맞지 않으면 ContractError를 낸다.
    """
    if name not in _CONTRACTS:
        raise ValueError(f"알 수 없는 계약 이름이다. 쓸 수 있는 값: {', '.join(CONTRACT_NAMES)}")
    _, model = _CONTRACTS[name]

    if not _is_storable_json(data):
        # 어느 칸인지 알리지 않는다. 경로에 입력 키가 들어갈 수 있기 때문이다.
        raise ContractError(name, [Violation("(root)", "json")])

    violations = [v for e in _validators()[name].iter_errors(data) for v in _from_schema_error(e)]
    if not violations:
        violations = _extra_violations(name, data)
    if violations:
        raise ContractError(name, violations)

    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        # 생성 모델은 schema와 다른 검사기라 ①~③을 통과해도 여기서 걸릴 수 있다. 알려진 경우
        # (끝에 \n이 붙은 ID, 숫자 필드의 NaN)는 앞 단계로 옮겼고, 남은 경우는 확인하지 못했다.
        # 방어 코드로 둔다. 여기서 나는 rule은 Pydantic 오류 이름이라 rule 약속(JSON Schema
        # 키워드·json·equals_ocsf_class) 밖이다. 입력 값이 든 원래 예외는 감춘다.
        raise ContractError(name, map(_from_pydantic_error, exc.errors())) from None


def _is_storable_json(data: Any) -> bool:
    """data가 PostgreSQL에 그대로 넣을 수 있는 JSON 값인지 본다.

    ① json.dumps(allow_nan=False): bytes·datetime·set(TypeError), 순환 참조·NaN·Infinity(ValueError)
    ② ①을 통과한 뒤 모든 dict 키가 문자열인지, 키와 문자열 값에 NUL이 없는지 본다.
       json.dumps는 int·float·bool·None 키를 문자열로 바꿔 통과시키고, PostgreSQL은 text와 jsonb
       모두 NUL을 거부한다. 순환 참조는 ①에서 걸렀으므로 ②는 끝난다. 깊게 중첩된 값에서
       RecursionError가 나지 않게 재귀 함수 대신 스택으로 돈다.
    """
    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError):
        return False

    stack = [data]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            if "\x00" in value:
                return False
        elif isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or "\x00" in key:
                    return False
                stack.append(item)
        elif isinstance(value, list | tuple):
            stack.extend(value)
    return True


def _extra_violations(name: str, data: dict[str, Any]) -> list[Violation]:
    """JSON Schema로 쓸 수 없는 규칙. schema 검사를 통과한 data만 받는다."""
    if name == "event" and data["ocsf_class"] != data["ocsf"]["class_uid"]:
        return [Violation("ocsf.class_uid", "equals_ocsf_class")]
    return []


@cache
def _compile_pattern(pattern: str) -> re.Pattern[str]:
    """schema pattern을 Python 정규식으로 컴파일한다. 끝의 $는 \\Z로 바꾼다.

    jsonschema는 pattern을 re.search로 검사하는데, Python의 $는 마지막 \\n 앞에서도 맞는다.
    그래서 "alt_<uuid>\\n"이 ^alt_…$를 통과한다. schema에 \\Z를 쓰지 않는 것은 ECMA 정규식과
    Rust regex(Pydantic)가 \\Z를 모르기 때문이다.
    이스케이프된 \\$(앞의 백슬래시가 홀수 개)는 그대로 둔다.
    """
    if pattern.endswith("$"):
        body = pattern[:-1]
        if (len(body) - len(body.rstrip("\\"))) % 2 == 0:
            pattern = body + r"\Z"
    return re.compile(pattern)


def _pattern(
    validator: Validator, pattern: str, instance: Any, schema: Any
) -> Iterator[ValidationError]:
    if validator.is_type(instance, "string") and not _compile_pattern(pattern).search(instance):
        # 메시지에 입력 값을 넣지 않는다.
        yield ValidationError(f"does not match {pattern!r}")


# pattern 검사만 바꾼 Draft 7 검사기. 위반 rule 이름은 그대로 "pattern"이다.
_ContractValidator = validators.extend(Draft7Validator, {"pattern": _pattern})


@cache
def _validators() -> dict[str, Validator]:
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
        name: _ContractValidator(registry.contents(schema_file), registry=registry)
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
