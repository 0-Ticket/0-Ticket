"""소스별 매핑표(YAML)를 읽고 원본 hit에 적용한다(D-060, D-061).

표 한 파일은 `entries`(target·from·transform·required), 선택 `entities`(type·role·from·transform),
선택 `detect`를 가진다.
`common.yaml`은 소스와 무관한 단순 대응이고 그 밖의 파일은 소스 이름이 파일 이름이다.
"""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, get_args

import yaml

from soc.contracts.generated.common.entity_schema import Entity as EntityContract
from soc.normalize.errors import NormalizeError
from soc.normalize.paths import read_value
from soc.normalize.transforms import COPY, ENTITY_TRANSFORMS, TRANSFORMS, is_text

ENTITY_TYPES = frozenset(get_args(EntityContract.model_fields["type"].annotation))
# role은 `Literal[...] | None`이라 한 겹 더 풀어 문자열만 모은다
ENTITY_ROLES = frozenset(
    role
    for part in get_args(EntityContract.model_fields["role"].annotation)
    for role in get_args(part)
)
# ip 변환이 틀린 값을 만났을 때 누락으로 적을 OCSF 경로. role이 정한다
_IP_GAPS = {"src": "evidences[].src_endpoint.ip", "dst": "evidences[].dst_endpoint.ip"}

TABLE_DIR = Path(__file__).parent / "mapping_tables"
COMMON = "common"
_TABLE_KEYS = {"detect", "entries", "entities"}
_ENTRY_KEYS = {"target", "from", "transform", "required"}
_ENTITY_KEYS = {"type", "role", "from", "transform"}


class MappingTableError(Exception):
    """매핑표 파일이 형식에 맞지 않는다. 메시지에는 파일 이름과 틀린 곳만 넣는다."""


@dataclass(frozen=True)
class Entry:
    """표의 항목 하나.

    Attributes:
        target: OCSF 경로. 배열 속성은 `evidences[].dst_endpoint.ip`처럼 `[]`를 붙인다.
        sources: 원본 경로 목록. 앞에서부터 처음 있는 값을 쓴다. `$.`로 시작하면 hit 기준이다.
        transform: 등록된 변환 이름. 없으면 문자열을 그대로 옮긴다.
        required: 값을 얻지 못하면 partial로 기록할 항목.
    """

    target: str
    sources: tuple[str, ...]
    transform: str | None = None
    required: bool = False


@dataclass(frozen=True)
class EntityRule:
    """엔티티 항목 하나.

    Attributes:
        type: 엔티티 종류(계약의 허용 값). 변환이 바꿀 수 있다.
        role: 엔티티 역할(계약의 허용 값). 생략하면 None.
        sources: 원본 경로 목록. 앞에서부터 처음 있는 값을 쓴다.
        transform: 등록된 엔티티 변환 이름. 없으면 문자열을 그대로 쓴다.
    """

    type: str
    role: str | None
    sources: tuple[str, ...]
    transform: str | None = None


@dataclass(frozen=True)
class Condition:
    """detect 조건 하나. equals와 exists 중 하나만 가진다.

    Attributes:
        fields: 읽을 원본 경로 목록(`from`과 같은 문법). 앞에서부터 처음 있는 값을 쓴다.
        equals: 필드 값이 이 문자열과 같으면 맞다.
        exists: True면 필드 값이 있으면(None이 아니면) 맞다.
    """

    fields: tuple[str, ...]
    equals: str | None = None
    exists: bool = False


@dataclass(frozen=True)
class Table:
    """매핑표 하나.

    Attributes:
        name: 표 이름(파일 이름에서 확장자를 뗀 것).
        entries: 항목들. 적용 순서이자 missing_fields의 순서다.
        detect: 소스 판별 조건들. 하나라도 맞으면 이 소스다.
        entities: 엔티티 항목들. 적용 순서가 엔티티 목록의 순서다.
    """

    name: str
    entries: tuple[Entry, ...]
    detect: tuple[Condition, ...] = ()
    entities: tuple[EntityRule, ...] = ()


@dataclass
class Applied:
    """표를 원본 하나에 적용한 결과.

    Attributes:
        values: 얻은 값. target 경로 → 값.
        missing: 얻지 못한 required 항목의 target(표 순서).
        errors: 값이 있는데 변환이 읽지 못한 항목의 target.
    """

    values: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AppliedEntities:
    """엔티티 항목들을 원본 하나에 적용한 결과. 여러 표에 걸쳐 쌓을 수 있다.

    Attributes:
        entities: {"type", "value", "role"} 목록. 같은 것은 한 번만 둔다.
        missing: IP가 아니라서 얻지 못한 OCSF 경로. 같은 경로는 한 번만 둔다.
    """

    entities: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def load_tables(directory: Path | None = None) -> dict[str, Table]:
    """폴더의 모든 *.yaml을 읽어 검사한다. 같은 폴더는 한 번만 읽는다.

    Args:
        directory: 표 폴더. 없으면 src/soc/normalize/mapping_tables/.

    Raises:
        MappingTableError: 형식이 틀렸거나 모르는 변환 이름이 있거나 common 표가 없다.
    """
    return _load(directory or TABLE_DIR)


@cache
def _load(directory: Path) -> dict[str, Table]:
    """폴더의 표를 읽는다(load_tables의 캐시 본체)."""
    tables: dict[str, Table] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            tables[path.stem] = parse_table(path.stem, document)
        except (yaml.YAMLError, UnicodeDecodeError) as error:
            raise MappingTableError(
                f"{path.name}: YAML을 읽을 수 없다 ({type(error).__name__})"
            ) from None
        except MappingTableError as error:
            raise MappingTableError(f"{path.name}: {error}") from None
    if COMMON not in tables:
        raise MappingTableError(f"{COMMON}.yaml이 없다")
    return tables


def parse_table(name: str, document: Any) -> Table:
    """YAML로 읽은 값 하나를 검사해 Table로 만든다.

    Args:
        name: 표 이름.
        document: yaml.safe_load의 결과.

    Raises:
        MappingTableError: 키·값 형식이 틀렸거나 변환 이름이 등록돼 있지 않다.
    """
    if not isinstance(document, dict) or not set(document) <= _TABLE_KEYS:
        raise MappingTableError("최상위는 detect와 entries만 가진 객체여야 한다")
    raw_entries = document.get("entries")
    if not isinstance(raw_entries, list):
        raise MappingTableError("entries는 목록이어야 한다")
    entries = tuple(_entry(item) for item in raw_entries)
    targets = [entry.target for entry in entries]
    if len(set(targets)) != len(targets):
        raise MappingTableError("target이 겹친다")
    raw_detect = document.get("detect", [])
    if not isinstance(raw_detect, list):
        raise MappingTableError("detect는 목록이어야 한다")
    raw_entities = document.get("entities", [])
    if not isinstance(raw_entities, list):
        raise MappingTableError("entities는 목록이어야 한다")
    return Table(
        name,
        entries,
        tuple(_condition(item) for item in raw_detect),
        tuple(_entity(item) for item in raw_entities),
    )


def _entry(item: Any) -> Entry:
    """항목 하나를 검사한다."""
    if not isinstance(item, dict) or not set(item) <= _ENTRY_KEYS:
        raise MappingTableError("항목은 target, from, transform, required만 가진 객체여야 한다")
    target, sources = item.get("target"), item.get("from")
    if not _is_name(target):
        raise MappingTableError("target은 비어 있지 않은 문자열이어야 한다")
    if not isinstance(sources, list) or not sources or not all(_is_name(p) for p in sources):
        raise MappingTableError(f"{target}: from은 경로 문자열의 비어 있지 않은 목록이어야 한다")
    transform = item.get("transform")
    if transform is not None and transform not in TRANSFORMS:
        raise MappingTableError(f"{target}: 등록되지 않은 transform {transform}")
    required = item.get("required", False)
    if not isinstance(required, bool):
        raise MappingTableError(f"{target}: required는 true 또는 false여야 한다")
    return Entry(target, tuple(sources), transform, required)


def _entity(item: Any) -> EntityRule:
    """엔티티 항목 하나를 검사한다. type·role은 계약의 허용 값이어야 한다."""
    if not isinstance(item, dict) or not set(item) <= _ENTITY_KEYS:
        raise MappingTableError("엔티티 항목은 type, role, from, transform만 가진 객체여야 한다")
    entity_type, role, sources = item.get("type"), item.get("role"), item.get("from")
    if entity_type not in ENTITY_TYPES:
        raise MappingTableError(f"계약에 없는 엔티티 type {entity_type!r}")
    if role is not None and role not in ENTITY_ROLES:
        raise MappingTableError(f"{entity_type}: 계약에 없는 role {role!r}")
    if not isinstance(sources, list) or not sources or not all(_is_name(p) for p in sources):
        raise MappingTableError(
            f"{entity_type}: from은 경로 문자열의 비어 있지 않은 목록이어야 한다"
        )
    transform = item.get("transform")
    if transform is not None and transform not in ENTITY_TRANSFORMS:
        raise MappingTableError(f"{entity_type}: 등록되지 않은 엔티티 transform {transform}")
    if transform == "ip" and role not in _IP_GAPS:
        raise MappingTableError(f"{entity_type}: ip 변환은 role이 src 또는 dst여야 한다")
    return EntityRule(entity_type, role, tuple(sources), transform)


def _condition(item: Any) -> Condition:
    """detect 조건 하나를 검사한다. `field`(문자열 또는 목록)와 `equals`·`exists: true` 중 하나."""
    raw = item.get("field") if isinstance(item, dict) else None
    fields = tuple(raw) if isinstance(raw, list) and raw else (raw,)
    if not all(_is_name(name) for name in fields):
        raise MappingTableError("detect 조건은 field를 가져야 한다")
    rest = set(item) - {"field"}
    if rest == {"equals"} and isinstance(item["equals"], str):
        return Condition(fields, equals=item["equals"])
    if rest == {"exists"} and item["exists"] is True:
        return Condition(fields, exists=True)
    raise MappingTableError("detect 조건은 field와 equals(문자열) 또는 exists(true)만 가진다")


def _is_name(value: Any) -> bool:
    """비어 있지 않은 문자열인가."""
    return isinstance(value, str) and bool(value)


def _read(hit: dict[str, Any], path: str) -> Any:
    """`$.`로 시작하면 hit 기준, 아니면 _source 기준으로 값을 읽는다."""
    if path.startswith("$."):
        return read_value(hit, path[2:])
    source = hit.get("_source")
    return read_value(source, path) if isinstance(source, dict) else None


def apply_table(table: Table, hit: dict[str, Any]) -> Applied:
    """표의 항목을 순서대로 원본 hit에 적용한다.

    `from`은 변환이 받는 값(accepts)이 처음 있는 경로를 고른다. 값이 있는데 읽지 못하면
    다음 경로로 넘어가지 않고 errors에 기록한다.

    Args:
        table: 적용할 표.
        hit: raw.original(_index, _id, _source를 가진 ELK hit).
    """
    applied = Applied()
    for entry in table.entries:
        transform = TRANSFORMS[entry.transform] if entry.transform else COPY
        found = next(
            (
                value
                for value in (_read(hit, path) for path in entry.sources)
                if value is not None and transform.accepts(value)
            ),
            None,
        )
        if found is None:
            value = None
        else:
            try:
                value = transform.convert(found)
            except NormalizeError:
                applied.errors.append(entry.target)
                continue
        if value is None:
            if entry.required:
                applied.missing.append(entry.target)
        else:
            applied.values[entry.target] = value
    return applied


def apply_entities(
    table: Table, hit: dict[str, Any], applied: AppliedEntities | None = None
) -> AppliedEntities:
    """표의 엔티티 항목을 순서대로 원본 hit에 적용한다.

    `from`은 처음 있는 문자열 값을 쓴다. 값이 있는데 변환이 읽지 못하면(ip가 아님) 다음 경로로
    넘어가지 않고 엔티티를 만들지 않으며, ip 변환이면 role에서 누락 경로를 기록한다.

    Args:
        table: 적용할 표.
        hit: raw.original.
        applied: 앞 표의 결과. 주면 이어서 쌓는다(같은 엔티티·경로는 한 번만).
    """
    applied = applied or AppliedEntities()
    for rule in table.entities:
        value = next((v for v in (_read(hit, path) for path in rule.sources) if is_text(v)), None)
        if value is None:
            continue
        entity_type = rule.type
        if rule.transform:
            try:
                entity_type, value = ENTITY_TRANSFORMS[rule.transform].convert(entity_type, value)
            except NormalizeError:
                gap = _IP_GAPS.get(rule.role or "")
                if gap and gap not in applied.missing:
                    applied.missing.append(gap)
                continue
        entity = {"type": entity_type, "value": value, "role": rule.role}
        if entity not in applied.entities:
            applied.entities.append(entity)
    return applied


def matching_source(tables: dict[str, Table], hit: dict[str, Any]) -> str | None:
    """detect 조건이 맞는 첫 소스 표의 이름을 돌려준다. 표 이름 순서로 본다. 없으면 None.

    Args:
        tables: load_tables의 결과. common은 판별하지 않는다.
        hit: raw.original.
    """
    for name, table in sorted(tables.items()):
        if name != COMMON and any(_matches(condition, hit) for condition in table.detect):
            return name
    return None


def _matches(condition: Condition, hit: dict[str, Any]) -> bool:
    """조건 하나가 hit에 맞는가. equals는 필드 목록에서 처음 있는 문자열 값으로 비교한다."""
    values = [_read(hit, path) for path in condition.fields]
    if condition.exists:
        return any(value is not None for value in values)
    return next((value for value in values if is_text(value)), None) == condition.equals
