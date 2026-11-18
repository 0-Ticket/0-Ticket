"""소스별 매핑표(YAML)를 읽고 원본 hit에 적용한다(D-060, D-061).

표 한 파일은 `entries`(target·from·transform·required)와 선택 `detect`를 가진다.
`common.yaml`은 소스와 무관한 단순 대응이고 그 밖의 파일은 소스 이름이 파일 이름이다.
"""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from soc.normalize.errors import NormalizeError
from soc.normalize.paths import read_value
from soc.normalize.transforms import COPY, TRANSFORMS

TABLE_DIR = Path(__file__).parent / "mapping_tables"
COMMON = "common"
_TABLE_KEYS = {"detect", "entries"}
_ENTRY_KEYS = {"target", "from", "transform", "required"}


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
class Condition:
    """detect 조건 하나. equals와 exists 중 하나만 가진다.

    Attributes:
        field: 읽을 원본 경로(`from`과 같은 문법).
        equals: 필드 값이 이 문자열과 같으면 맞다.
        exists: True면 필드 값이 있으면(None이 아니면) 맞다.
    """

    field: str
    equals: str | None = None
    exists: bool = False


@dataclass(frozen=True)
class Table:
    """매핑표 하나.

    Attributes:
        name: 표 이름(파일 이름에서 확장자를 뗀 것).
        entries: 항목들. 적용 순서이자 missing_fields의 순서다.
        detect: 소스 판별 조건들. 하나라도 맞으면 이 소스다.
    """

    name: str
    entries: tuple[Entry, ...]
    detect: tuple[Condition, ...] = ()


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
    return Table(name, entries, tuple(_condition(item) for item in raw_detect))


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


def _condition(item: Any) -> Condition:
    """detect 조건 하나를 검사한다. `field`와 `equals` 또는 `exists: true`만 허용한다."""
    if not isinstance(item, dict) or not _is_name(item.get("field")):
        raise MappingTableError("detect 조건은 field를 가져야 한다")
    rest = set(item) - {"field"}
    if rest == {"equals"} and isinstance(item["equals"], str):
        return Condition(item["field"], equals=item["equals"])
    if rest == {"exists"} and item["exists"] is True:
        return Condition(item["field"], exists=True)
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
    """조건 하나가 hit에 맞는가."""
    value = _read(hit, condition.field)
    return value is not None if condition.exists else value == condition.equals
