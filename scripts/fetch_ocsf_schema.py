"""OCSF 1.9.0 클래스 0·2004와 참조 객체 전체를 공식 API에서 받아 ocsf/에 고정한다.

    uv run python scripts/fetch_ocsf_schema.py

출처와 방법은 src/soc/normalize/ocsf/SOURCE.md에 있다.
받은 정의는 직접 고치지 않고 이 스크립트로 다시 만든다.
스키마 로더가 처리하지 않는 constraints 종류가 있으면 아무것도 쓰지 않고 실패한다.
"""

import json
import sys
from pathlib import Path
from typing import Any

import httpx

from soc.normalize.ocsf_schema import SUPPORTED_CONSTRAINTS

API = "https://schema.ocsf.io/api/1.9.0"
# 0·2004는 알럿(#328), 나머지는 이벤트 수집 설정 `class`가 쓰는 클래스(#340, D-067)
CLASSES = {
    "base_event": 0,
    "detection_finding": 2004,
    "compliance_finding": 2003,
    "authentication": 3002,
    "network_activity": 4001,
    "http_activity": 4002,
    "dns_activity": 4003,
    "api_activity": 6003,
}
OUT = Path(__file__).resolve().parent.parent / "src" / "soc" / "normalize" / "ocsf"


def fetch(client: httpx.Client, kind: str, name: str) -> dict[str, Any]:
    """클래스 또는 객체 정의 하나를 프로필 없이 받는다(상속은 서버가 풀어 준다).

    Args:
        client: HTTP 클라이언트.
        kind: "classes" 또는 "objects".
        name: 정의 이름. 예: "detection_finding", "win/reg_key".
    """
    response = client.get(f"{API}/{kind}/{name}", params={"profiles": ""})
    response.raise_for_status()
    return response.json()


def references(definition: dict[str, Any]) -> set[str]:
    """정의 속성이 가리키는 객체 이름을 모은다.

    Args:
        definition: 클래스 또는 객체 정의.
    """
    return {
        attribute["object_type"]
        for attribute in definition["attributes"].values()
        if attribute.get("type") == "object_t" and "object_type" in attribute
    }


def collect(client: httpx.Client) -> tuple[dict[int, dict[str, Any]], dict[str, dict[str, Any]]]:
    """클래스 두 개와 그 참조 객체를 object_type을 따라 모두 받는다.

    Args:
        client: HTTP 클라이언트.
    """
    classes = {uid: fetch(client, "classes", name) for name, uid in CLASSES.items()}
    objects: dict[str, dict[str, Any]] = {}
    pending = {name for definition in classes.values() for name in references(definition)}
    while pending:
        name = pending.pop()
        if name not in objects:
            objects[name] = fetch(client, "objects", name)
            pending |= references(objects[name]) - objects.keys()
    return classes, objects


def unsupported_constraints(*definitions: dict[str, Any]) -> set[str]:
    """스키마 로더가 처리하지 않는 constraints 종류를 돌려준다.

    Args:
        definitions: 클래스·객체 정의들.
    """
    kinds = {kind for definition in definitions for kind in definition.get("constraints", {})}
    return kinds - SUPPORTED_CONSTRAINTS


def write(path: Path, value: Any) -> None:
    """키를 정렬한 JSON으로 쓴다. 다시 받아도 같은 파일이 나온다.

    Args:
        path: 쓸 파일.
        value: JSON 값.
    """
    path.write_text(json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> int:
    """정의를 받아 검사하고 classes/0.json, classes/2004.json, objects.json을 쓴다."""
    with httpx.Client(timeout=30) as client:
        classes, objects = collect(client)
    bad = unsupported_constraints(*classes.values(), *objects.values())
    if bad:
        print(f"스키마 로더가 처리하지 않는 constraints 종류: {sorted(bad)}", file=sys.stderr)
        return 1
    for uid, definition in classes.items():
        write(OUT / "classes" / f"{uid}.json", definition)
    write(OUT / "objects.json", objects)
    print(f"classes={sorted(classes)} objects={len(objects)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
