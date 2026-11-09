"""프롬프트 5층 합성(#210). 아래층은 윗층을 대체하지 않고 덧붙이기만 한다.

1 공통(prompts/base.md) / 2 단계(prompts/l1.md·l2.md·l3.md) /
3 도메인(prompts/domains/<도메인>.md) / 4 작업(AgentTask.prompt) /
5 자동(고정 턴 문장, 출력 계약 요약, decided_at 안내).
합친 내용이 같으면 prompt_version(해시)도 같아야 하므로 호출마다 바뀌는 값은 넣지 않는다.
"""

import json
from functools import cache
from pathlib import Path
from typing import Any

from soc.agent.types import DOMAINS, AgentTask

# 계약 모듈에 계약 schema·최상위 필드를 조회하는 공개 함수가 없어
# 비공개 이름을 읽기만 한다(#209와 같음).
from soc.contracts.validate import _CONTRACTS, SCHEMA_DIR

PROMPT_DIR = Path(__file__).parent / "prompts"
_MAX_REF_HOPS = 100
_SCHEMA_HEADER = "출력 계약 JSON Schema:"


def compose_instructions(task: AgentTask, *, max_turns: int) -> str:
    layers = [_read("base.md"), _read(f"{task.stage}.md")]
    layers += [_read(f"domains/{domain}.md") for domain in DOMAINS if domain in task.domains]
    layers.append(task.prompt.text.strip())
    layers.append(_auto_layer(task.output_contract, max_turns))
    return "\n\n".join(layers)


def has_top_level_field(contract: str, field: str) -> bool:
    return field in _CONTRACTS[contract][1].model_fields


def _auto_layer(contract: str, max_turns: int) -> str:
    lines = [
        f"최대 {max_turns}턴 안에 답한다.",
        f"마지막 답은 출력 계약 {contract}를 따르는 JSON 객체 하나다. 최상위 필드:",
        *_contract_summary(contract),
        _SCHEMA_HEADER,
        _contract_schema(contract),
    ]
    if has_top_level_field(contract, "decided_at"):
        lines.append(
            "decided_at은 비워 둔다(null로 두거나 빼도 된다). 실행기가 현재 시각으로 채운다."
        )
    return "\n".join(lines)


@cache
def _contract_summary(contract: str) -> tuple[str, ...]:
    """최상위 필드마다 한 줄: 이름, 필수 여부, 타입, enum 값."""
    path = SCHEMA_DIR / _CONTRACTS[contract][0]
    schema = _load_json(path)
    required = set(schema.get("required", []))
    lines = []
    for name, prop in schema.get("properties", {}).items():
        prop = _resolve(prop, path)
        parts = ["필수" if name in required else "선택"]
        kind = prop.get("type")
        if kind:
            parts.append(" 또는 ".join(kind) if isinstance(kind, list) else str(kind))
        line = f"- {name} ({', '.join(parts)})"
        values = prop.get("enum", [prop["const"]] if "const" in prop else None)
        if values:
            line += ": " + " | ".join(json.dumps(v, ensure_ascii=False) for v in values)
        lines.append(line)
    return tuple(lines)


@cache
def _contract_schema(contract: str) -> str:
    path = SCHEMA_DIR / _CONTRACTS[contract][0]
    schema = _resolve(_load_json(path), path)
    return json.dumps(schema, ensure_ascii=False, sort_keys=True)


def _resolve(value: Any, path: Path, ref_hops: int = 0) -> Any:
    """dict·list 전체의 `파일#/포인터` $ref를 현재 경로 100홉까지 해소한다."""
    if isinstance(value, list):
        return [_resolve(item, path, ref_hops) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        if ref_hops >= _MAX_REF_HOPS:
            raise ValueError(f"$ref 해소가 {_MAX_REF_HOPS}홉을 넘는다")
        file, _, pointer = value["$ref"].partition("#")
        ref_path = (path.parent / file).resolve() if file else path
        target: Any = _load_json(ref_path)
        for part in [p for p in pointer.split("/") if p]:
            target = target[part]
        merged = {**target, **{k: item for k, item in value.items() if k != "$ref"}}
        return _resolve(merged, ref_path, ref_hops + 1)
    return {key: _resolve(item, path, ref_hops) for key, item in value.items()}


@cache
def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def _read(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()
