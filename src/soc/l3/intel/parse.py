"""받은 바이트를 저장할 항목으로 바꾼다. 형식이 기대와 다르면 그 출처 전체를 실패로 처리한다."""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.parsers import expat

from soc.l3.intel.clean import clean_text
from soc.l3.intel.errors import IntelError

# Hunt 계약의 기법 ID 모양과 같다. 끝의 \n을 받지 않도록 fullmatch로 비교한다.
TECHNIQUE_ID = re.compile(r"T[0-9]{4}(\.[0-9]{3})?")
_CVE_ID = re.compile(r"CVE-[0-9]{4}-[0-9]{4,}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class NewsItem:
    source_ref: str
    title: str
    summary: str
    link: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class Technique:
    technique_id: str
    name: str
    tactics: tuple[str, ...]
    # 로컬 조회 도구용(#311). 설명은 정리한 평문, 탐지 데이터 소스는 data component 이름
    # (중복 없이 이름순)
    description: str = ""
    detection_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class KevEntry:
    cve_id: str
    vulnerability_name: str
    short_description: str
    vendor_project: str
    product: str
    date_added: date
    due_date: date | None
    known_ransomware_use: str
    required_action: str


@dataclass(frozen=True)
class KevCatalog:
    catalog_version: str
    released_at: datetime | None
    items: list[NewsItem]
    entries: list[KevEntry]


# --- RSS ---


class _DoctypeFound(Exception):
    pass


def _reject_doctype(data: bytes) -> None:
    """DOCTYPE이 있으면 doctype 실패. 엔티티 확장을 막는다.

    바이트 검색이 아니라 expat가 문서를 읽으며 알려 준다. 인코딩(UTF-16 등)과 상관없이 막힌다.
    """

    def found(*_: Any) -> None:
        raise _DoctypeFound

    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = found
    try:
        parser.Parse(data, True)
    except _DoctypeFound:
        raise IntelError("doctype") from None
    except expat.ExpatError:
        raise IntelError("parse") from None


def _text(element: ET.Element, tag: str) -> str | None:
    found = element.find(tag)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _rss_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    # "-0000"(시간대 모름)은 시간대 없는 값으로 온다. RFC 5322에 따라 UTC로 본다.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_rss(data: bytes, *, summary_max_chars: int) -> list[NewsItem]:
    """RSS 2.0의 channel/item. 본문(content:encoded)은 읽지 않는다.

    source_ref는 guid, 없으면 link. 둘 다 없거나 정리한 제목이 빈 항목은 버린다.
    """
    _reject_doctype(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise IntelError("parse") from None
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise IntelError("parse")

    items = []
    for item in channel.findall("item"):
        link = _text(item, "link")
        source_ref = _text(item, "guid") or link
        title = clean_text(_text(item, "title") or "")
        if source_ref is None or not title:
            continue
        items.append(
            NewsItem(
                source_ref=source_ref,
                title=title,
                summary=clean_text(_text(item, "description") or "", summary_max_chars),
                link=link,
                published_at=_rss_date(_text(item, "pubDate")),
            )
        )
    return items


# --- CISA KEV ---


def _load_json(data: bytes) -> Any:
    try:
        return json.loads(data)
    except (ValueError, RecursionError):
        raise IntelError("parse") from None


def _str(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise IntelError("parse")
    return value


def _optional_date(value: Any) -> date | None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _released_at(value: Any) -> datetime | None:
    """카탈로그 릴리스 시각. 읽지 못하면 None이다(수집 자체를 막지 않는다)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_kev_catalog(data: bytes, *, summary_max_chars: int) -> KevCatalog:
    """KEV 카탈로그. 항목마다 링크가 없고 dateAdded는 날짜만 있다(00:00 UTC).

    items는 threat_news에, entries와 카탈로그 정보는 kev_entries·intel_source_state에 저장한다
    (#311).
    """
    catalog = _load_json(data)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("vulnerabilities"), list):
        raise IntelError("parse")
    version = clean_text(_str(catalog, "catalogVersion"))
    if not version:
        raise IntelError("parse")

    items = []
    entries = []
    for record in catalog["vulnerabilities"]:
        if not isinstance(record, dict):
            raise IntelError("parse")
        cve_id = _str(record, "cveID")
        added = _str(record, "dateAdded")
        if not _CVE_ID.fullmatch(cve_id) or not _DATE.fullmatch(added):
            raise IntelError("parse")
        try:
            added_date = date.fromisoformat(added)
        except ValueError:
            raise IntelError("parse") from None
        title = clean_text(_str(record, "vulnerabilityName"))
        ransomware = clean_text(_str(record, "knownRansomwareCampaignUse"))
        if not title or not ransomware:
            raise IntelError("parse")
        summary = clean_text(_str(record, "shortDescription"), summary_max_chars)
        items.append(
            NewsItem(
                source_ref=cve_id,
                title=title,
                summary=summary,
                link=None,
                published_at=datetime.combine(added_date, datetime.min.time(), UTC),
            )
        )
        entries.append(
            KevEntry(
                cve_id=cve_id,
                vulnerability_name=title,
                short_description=summary,
                vendor_project=clean_text(_str(record, "vendorProject")),
                product=clean_text(_str(record, "product")),
                date_added=added_date,
                due_date=_optional_date(record.get("dueDate")),
                known_ransomware_use=ransomware,
                required_action=clean_text(_str(record, "requiredAction"), summary_max_chars),
            )
        )
    return KevCatalog(
        catalog_version=version,
        released_at=_released_at(catalog.get("dateReleased")),
        items=items,
        entries=entries,
    )


def parse_kev(data: bytes, *, summary_max_chars: int) -> list[NewsItem]:
    """KEV 카탈로그의 항목을 뉴스 항목으로만 돌려준다."""
    return parse_kev_catalog(data, summary_max_chars=summary_max_chars).items


# --- ATT&CK ---


def parse_attack(
    data: bytes, *, version: str, description_max_chars: int = 1000
) -> list[Technique]:
    """STIX 번들에서 폐기(revoked)·대체(x_mitre_deprecated)되지 않은 attack-pattern만 꺼낸다.

    컬렉션의 x_mitre_version이 설정 버전과 다르면 version_mismatch다.
    설명과 탐지 데이터 소스도 함께 꺼낸다(#311).
    """
    bundle = _load_json(data)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("objects"), list):
        raise IntelError("parse")
    objects = bundle["objects"]
    if not all(isinstance(o, dict) for o in objects):
        raise IntelError("parse")

    collections = [o for o in objects if o.get("type") == "x-mitre-collection"]
    if len(collections) != 1:
        raise IntelError("parse")
    if collections[0].get("x_mitre_version") != version:
        raise IntelError("version_mismatch")

    techniques: dict[str, Technique] = {}
    stix_ids: dict[str, str] = {}
    for obj in objects:
        if obj.get("type") != "attack-pattern" or _is_dead(obj):
            continue
        technique = _technique(obj, description_max_chars)
        if technique.technique_id in techniques:
            raise IntelError("parse")
        techniques[technique.technique_id] = technique
        stix_ids[str(obj.get("id"))] = technique.technique_id

    sources = _detection_sources(objects, stix_ids)
    return [
        replace(t, detection_sources=tuple(sorted(sources.get(t.technique_id, ()))))
        for t in techniques.values()
    ]


def _is_dead(obj: dict[str, Any]) -> bool:
    return obj.get("revoked") is True or obj.get("x_mitre_deprecated") is True


def _refs(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key, [])
    if not isinstance(value, list):
        raise IntelError("parse")
    return value


def _detection_sources(
    objects: list[dict[str, Any]], technique_ids: dict[str, str]
) -> dict[str, set[str]]:
    """기법 ← detects ← 탐지 전략 → analytic → data component 이름.

    ATT&CK 20.0은 기법에 옛 x_mitre_data_sources가 없고 이 관계로 이어진다.
    가리키는 객체가 없거나 폐기됐으면 건너뛴다.
    """
    components: dict[str, str] = {}
    analytics: dict[str, list[str]] = {}
    strategies: dict[str, list[str]] = {}
    for obj in objects:
        kind = obj.get("type")
        if kind not in ("x-mitre-data-component", "x-mitre-analytic", "x-mitre-detection-strategy"):
            continue
        if _is_dead(obj):
            continue
        key = str(obj.get("id"))
        if kind == "x-mitre-data-component":
            name = obj.get("name")
            if not isinstance(name, str):
                raise IntelError("parse")
            components[key] = clean_text(name)
        elif kind == "x-mitre-analytic":
            refs = []
            for ref in _refs(obj, "x_mitre_log_source_references"):
                target = ref.get("x_mitre_data_component_ref") if isinstance(ref, dict) else None
                if not isinstance(target, str):
                    raise IntelError("parse")
                refs.append(target)
            analytics[key] = refs
        else:
            refs = _refs(obj, "x_mitre_analytic_refs")
            if not all(isinstance(r, str) for r in refs):
                raise IntelError("parse")
            strategies[key] = refs

    found: dict[str, set[str]] = {}
    for obj in objects:
        if obj.get("type") != "relationship" or obj.get("relationship_type") != "detects":
            continue
        if _is_dead(obj):
            continue
        technique_id = technique_ids.get(str(obj.get("target_ref")))
        strategy = strategies.get(str(obj.get("source_ref")))
        if technique_id is None or strategy is None:
            continue
        for analytic in strategy:
            for component in analytics.get(analytic, ()):
                name = components.get(component)
                if name:
                    found.setdefault(technique_id, set()).add(name)
    return found


def _technique(obj: dict[str, Any], description_max_chars: int) -> Technique:
    references = obj.get("external_references")
    phases = obj.get("kill_chain_phases")
    if not isinstance(references, list) or not isinstance(phases, list):
        raise IntelError("parse")
    ids = [
        r.get("external_id")
        for r in references
        if isinstance(r, dict) and r.get("source_name") == "mitre-attack"
    ]
    if len(ids) != 1 or not isinstance(ids[0], str) or not TECHNIQUE_ID.fullmatch(ids[0]):
        raise IntelError("parse")
    name = obj.get("name")
    if not isinstance(name, str) or not clean_text(name):
        raise IntelError("parse")
    tactics = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise IntelError("parse")
        if phase.get("kill_chain_name") != "mitre-attack":
            continue
        tactic = phase.get("phase_name")
        if not isinstance(tactic, str) or not tactic:
            raise IntelError("parse")
        tactics.append(tactic)
    description = obj.get("description", "")
    if not isinstance(description, str):
        raise IntelError("parse")
    return Technique(
        technique_id=ids[0],
        name=clean_text(name),
        tactics=tuple(tactics),
        description=clean_text(description, description_max_chars),
    )
