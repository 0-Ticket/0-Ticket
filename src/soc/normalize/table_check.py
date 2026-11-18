"""매핑표가 고정한 OCSF 스키마와 맞는지 검사한다(D-061). pytest가 저장소의 표 전체에 돌린다.

검사: target이 클래스 정의에 있는가, 변환이 내보낼 수 있는 값이 target enum 안인가,
common과 소스별 표를 합쳐 클래스의 필수 속성이 채워지는가. 모르는 변환 이름은 표를 읽을 때 오류다.
"""

from soc.normalize.ocsf_schema import field_definition, required_children
from soc.normalize.tables import COMMON, Table
from soc.normalize.transforms import TRANSFORMS

CLASS_UID = 2004
# 표가 아니라 코드가 채우는 2004 경로. 하위 전체를 코드가 맡는 것은 그 경로 하나만 적는다
CODE_FILLED = frozenset(
    {
        "activity_id",
        "category_uid",
        "class_uid",
        "type_uid",
        "metadata",
        "finding_info.analytic.type_id",
    }
)


def check_tables(tables: dict[str, Table], class_uid: int = CLASS_UID) -> list[str]:
    """표 전체를 검사해 문제 목록을 돌려준다. 비어 있으면 통과다.

    Args:
        tables: load_tables의 결과.
        class_uid: 표가 채우는 OCSF 클래스. 정규화 Alert는 2004다.

    Returns:
        "종류 [표 이름] 경로" 꼴의 문제 문장들.
    """
    problems: list[str] = []
    for table in tables.values():
        problems += _target_problems(table, class_uid)
    common = tables[COMMON]
    scopes = [("common", [common])]
    scopes += [(f"common+{n}", [common, t]) for n, t in sorted(tables.items()) if n != COMMON]
    for scope, group in scopes:
        problems += _missing_required(scope, group, class_uid)
    return list(dict.fromkeys(problems))


def _target_problems(table: Table, class_uid: int) -> list[str]:
    """표의 target이 스키마에 있는지, 변환 값이 enum 안인지 본다."""
    problems = []
    for entry in table.entries:
        attribute = field_definition(class_uid, entry.target)
        if attribute is None:
            problems.append(f"unknown_target [{table.name}] {entry.target}")
            continue
        values = TRANSFORMS[entry.transform].values if entry.transform else None
        if values is not None and "enum" in attribute:
            outside = sorted(values - set(attribute["enum"]))
            if outside:
                problems.append(
                    f"bad_enum [{table.name}] {entry.target}: {','.join(outside)} not in enum"
                )
    return problems


def _missing_required(scope: str, group: list[Table], class_uid: int) -> list[str]:
    """표들과 코드 채움 목록을 합쳐 필수 속성이 모두 채워지는지 본다.

    class 최상위 필수는 모두 요구하고, 안쪽 객체의 필수 자식은 그 객체가 채워질 때만 요구한다.
    """
    filled = {entry.target.replace("[]", "") for table in group for entry in table.entries}
    filled |= CODE_FILLED
    problems: list[str] = []

    def covered(path: str) -> bool:
        return any(item == path or item.startswith(path + ".") for item in filled) or any(
            path.startswith(owner + ".") for owner in CODE_FILLED
        )

    def walk(prefix: str) -> None:
        for name in required_children(class_uid, prefix):
            path = f"{prefix}.{name}" if prefix else name
            if not covered(path):
                problems.append(f"missing_required [{scope}] {path}")
        below = prefix + "." if prefix else ""
        children = {item[len(below) :].split(".")[0] for item in filled if item.startswith(below)}
        for name in sorted(children):
            path = f"{below}{name}"
            if path not in CODE_FILLED and required_children(class_uid, path):
                walk(path)

    walk("")
    return problems
