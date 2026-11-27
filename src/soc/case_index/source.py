"""Case 색인의 이름·ID 규칙·승인 당시 Artifact 선택(#391, D-084). 가벼운 상수와 SQL만 둔다.

#392의 검색 도구(D-087)도 이 모듈을 가져다 쓴다. 임베더·Qdrant·L2를 import하지 않는다.
"""

# Qdrant 컬렉션 용도(컬렉션 이름은 용도·모델·revision에서 파생한다, D-031)
PURPOSE = "confirmed_cases"

_PREFIX = "cas_"

# 승인 당시 Artifact는 그 Incident의 최신 Artifact다. confirmed Incident를 재분석하는 경로가 없어
# (incidents.status를 바꾸는 코드는 모두 confirmed를 건드리지 않는다) 승인 때의 마지막 Artifact가
# 그대로 최신이다. DB가 이를 강제하지는 않는다. confirmed 재분석을 만들면 이 기준을 다시 정한다
# (그때는 차수를 대기 행에 복사한다). incident_artifacts의 SELECT 권한만 필요하고
# incident_reviews는 읽지 않는다(D-082). {columns}는 부르는 쪽이 고르는 열 이름(코드 상수)이다.
LATEST_ARTIFACT_SQL = (
    "SELECT {columns} FROM incident_artifacts WHERE incident_id = %s "
    "ORDER BY analysis_round DESC LIMIT 1"
)
# 같은 기준을 Case 여러 건에 한 번에 적용한다(#392 검색 도구). 파라미터는 Case ID 배열 하나다.
# 기준을 바꾸면 위 상수와 함께 바꾼다. {columns}는 코드 상수다(`a.`를 붙여 적는다).
LATEST_ARTIFACTS_SQL = (
    "SELECT DISTINCT ON (a.incident_id) {columns} FROM incident_artifacts a "
    "JOIN cases c ON c.incident_id = a.incident_id WHERE c.id = ANY(%s) "
    "ORDER BY a.incident_id, a.analysis_round DESC"
)


def point_id(case_id: str) -> str:
    """Case ID에서 `cas_`를 뗀 UUID. Qdrant point ID로 쓴다."""
    if not case_id.startswith(_PREFIX):
        raise ValueError("Case ID는 cas_로 시작한다")
    return case_id.removeprefix(_PREFIX)


def case_id_of(point: str) -> str:
    """Qdrant point ID를 Case ID로 되돌린다. 검색 hit는 이 값으로 PostgreSQL에서 다시 확인한다."""
    return _PREFIX + point
