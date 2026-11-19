"""Alert JSON 조립(D-066). 계약(Alert)의 최상위는 OCSF 문서이고 우리 쪽 값은 details에 있다.

DB 없는 순수 함수다. alerts 행(이전 계약 모양)에서 Alert JSON을 만들고(읽기 전용, 되돌리는
경로는 없다), JSON에서 time·severity·title을 읽는 헬퍼와 모델 입력용 변환을 함께 둔다.
"""

from typing import Any

from soc.contracts.event import assemble_event

# 컬럼에서 details로 옮기는 우리 쪽 값. 계약의 details 필수 키와 같다
DETAILS_KEYS = ("id", "raw_id", "rule_id", "entities", "assets", "triage")
UNKNOWN_ID = 0
_MAX_COLUMN_SEVERITY = 6


def assemble_alert(row: dict[str, Any]) -> dict[str, Any]:
    """alerts 행으로 Alert JSON을 만든다. 최상위는 `ocsf` 문서이고 우리 값은 `details`다.

    `title`·`time`·`severity` 컬럼은 읽지 않는다(ocsf 안에 있다). 받은 행은 바꾸지 않는다.

    Args:
        row: ocsf·details와 DETAILS_KEYS 컬럼을 가진 alerts 행.

    Raises:
        ValueError: ocsf에 details 키가 있거나 행의 details가 DETAILS_KEYS 이름을 쓸 때.
    """
    ocsf, extra = row["ocsf"], row["details"]
    if "details" in ocsf or set(extra) & set(DETAILS_KEYS):
        raise ValueError("details 키가 겹친다")
    return {**ocsf, "details": {**extra, **{key: row[key] for key in DETAILS_KEYS}}}


def contract_data(name: str, row: dict[str, Any]) -> dict[str, Any]:
    """DB 행을 계약 검증에 넘기는 모양으로 바꾼다. Alert·Event는 조립하고 그 밖은 행 그대로다."""
    if name == "alert":
        return assemble_alert(row)
    return assemble_event(row) if name == "event" else row


def alert_time(alert: dict[str, Any]) -> int:
    """Alert JSON(또는 ocsf 문서)의 시각. `start_time`, 없으면 `time`이다(epoch 밀리초).

    최상위 `time`은 OCSF 생성 시각이라 컬럼 `time`과 다르다. 변환은 하지 않는다.
    """
    return alert.get("start_time", alert["time"])


def alert_severity(alert: dict[str, Any]) -> int:
    """심각도 0~6. `severity_id`이고 범위 밖(99 Other 등)이나 없으면 0이다."""
    severity = alert.get("severity_id", UNKNOWN_ID)
    return severity if 0 <= severity <= _MAX_COLUMN_SEVERITY else UNKNOWN_ID


def alert_title(alert: dict[str, Any]) -> str:
    """한 줄 요약. `finding_info.title`, 없으면 `message`다."""
    return (alert.get("finding_info") or {}).get("title") or alert["message"]


def alert_rule_id(alert: dict[str, Any]) -> str | None:
    """SIEM 탐지 룰 ID. `finding_info.analytic.uid`, 없으면 None이다."""
    return ((alert.get("finding_info") or {}).get("analytic") or {}).get("uid")


def alert_model_input(alert: dict[str, Any]) -> dict[str, Any]:
    """Alert JSON을 L2 모델 입력용 이전 모양(평면 필드 + ocsf + details)으로 바꾼다.

    모델 입력은 이 변경으로 달라지지 않는다. `time`은 `start_time` 기준이다.
    """
    details = alert["details"]
    return {
        "id": details["id"],
        "raw_id": details["raw_id"],
        "time": alert_time(alert),
        "severity": alert_severity(alert),
        "title": alert_title(alert),
        "rule_id": details["rule_id"],
        "entities": details["entities"],
        "assets": details["assets"],
        "triage": details["triage"],
        "ocsf": {key: value for key, value in alert.items() if key != "details"},
        "details": {key: value for key, value in details.items() if key not in DETAILS_KEYS},
    }
