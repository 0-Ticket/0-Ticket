"""Event JSON 조립(D-068). 계약(Event)의 최상위는 OCSF 문서이고 우리 쪽 값은 details에 있다.

DB 없는 순수 함수다. events 행에서 Event JSON을 만들고(읽기 전용, 되돌리는 경로는 없다),
JSON에서 시각·클래스·요약을 읽는 헬퍼와 모델 입력용 변환을 함께 둔다. Alert의 `alert.py`와
같은 모양이다.
"""

from typing import Any

# 컬럼에서 details로 옮기는 우리 쪽 값. 계약의 details 필수 키와 같다
DETAILS_KEYS = ("id", "raw_id", "entities", "assets")
# 요약을 만들 값이 하나도 없을 때의 마지막 요약(3순위)
EMPTY_SUMMARY = "event"


def assemble_event(row: dict[str, Any]) -> dict[str, Any]:
    """events 행으로 Event JSON을 만든다. 최상위는 `ocsf` 문서이고 우리 값은 `details`다.

    `time`·`ocsf_class`·`summary` 컬럼은 읽지 않는다(ocsf 안에 있다). 받은 행은 바꾸지 않는다.

    Args:
        row: ocsf·details와 DETAILS_KEYS 컬럼을 가진 events 행.

    Raises:
        ValueError: ocsf에 details 키가 있거나 행의 details가 DETAILS_KEYS 이름을 쓸 때.
    """
    ocsf, extra = row["ocsf"], row["details"]
    if "details" in ocsf or set(extra) & set(DETAILS_KEYS):
        raise ValueError("details 키가 겹친다")
    return {**ocsf, "details": {**extra, **{key: row[key] for key in DETAILS_KEYS}}}


def event_time(event: dict[str, Any]) -> int:
    """Event JSON(또는 ocsf 문서)의 시각. `start_time`, 없으면 `time`이다(epoch 밀리초).

    개별 이벤트의 `time`은 활동 발생 시각이고 `start_time`은 집계 이벤트에만 있다.
    """
    return event.get("start_time", event["time"])


def event_class(event: dict[str, Any]) -> int:
    """OCSF 클래스 번호(`class_uid`)."""
    return event["class_uid"]


def event_summary(event: dict[str, Any]) -> str:
    """한 줄 요약. `message`이고 비어 있으면 "event"다."""
    return event.get("message") or EMPTY_SUMMARY


def event_model_input(event: dict[str, Any]) -> dict[str, Any]:
    """Event JSON을 L2 모델 입력용 이전 모양(평면 필드 + ocsf + details)으로 바꾼다.

    모델 입력의 칸 이름은 이 변경으로 달라지지 않는다. `time`은 `start_time` 기준이다.
    """
    details = event["details"]
    return {
        "id": details["id"],
        "raw_id": details["raw_id"],
        "time": event_time(event),
        "ocsf_class": event_class(event),
        "summary": event_summary(event),
        "entities": details["entities"],
        "assets": details["assets"],
        "ocsf": {key: value for key, value in event.items() if key != "details"},
        "details": {key: value for key, value in details.items() if key not in DETAILS_KEYS},
    }
