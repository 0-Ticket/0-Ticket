# OCSF 1.9.0 클래스·객체 정의

정의의 원본은 OCSF 스키마(github.com/ocsf/ocsf-schema, Apache License 2.0)다.
OCSF가 클래스별 JSON Schema 파일을 따로 배포하지 않아, OCSF 서버(schema.ocsf.io)가 주는 1.9.0 정의로
`ocsf_schema.validate_ocsf`가 검사한다(D-007).

## 고정한 정의(#328, 2026-11-18)

- `classes/0.json`(Base Event), `classes/2004.json`(Detection Finding)과, 이 두 클래스가 `object_type`으로
  직접·간접 참조하는 객체 127개(`objects.json`, 객체 이름을 키로 한 파일 하나)를 공식 정의 그대로 둔다.
  속성마다 `type`, `requirement`, `is_array`, `object_type`, `enum`(값과 설명), 설명 문장이 있고
  클래스·객체의 `constraints`도 있다. 직접 고치지 않는다. 바꿀 때는 아래 명령으로 다시 만든다.
- 받는 방법: `uv run python scripts/fetch_ocsf_schema.py`
  - `https://schema.ocsf.io/api/1.9.0/classes/<이름>?profiles=`로 `base_event`, `detection_finding`을 받고,
    `https://schema.ocsf.io/api/1.9.0/objects/<이름>?profiles=`로 참조 객체를 빠짐없이 따라가 받는다.
    서버가 상속을 풀어 준 정의다. 객체 이름의 `/`(예: `win/reg_key`)는 키 그대로 둔다.
  - 프로필 없이(`profiles=`) 받으므로 프로필 속성(cloud 등)은 없다. 필요해지면 해당 프로필로 다시 받는다.
  - 키를 정렬해 쓰므로 같은 정의면 같은 파일이 나온다. 스키마 로더(`ocsf_schema.py`)가 처리하지 않는
    `constraints` 종류(처리하는 것: `at_least_one`, `just_one`)가 있으면 아무것도 쓰지 않고 실패한다.
- 단일 "컴파일본" 파일은 쓰지 않는다. `https://schema.ocsf.io/export/schema`는 1.9.0에서 프로필 충돌
  (`process.euid`가 여러 프로필에 있음)로 400을 돌려준다(2026-11-18 확인). 그래서 클래스·객체 API를 따라간다.
- 검증이 줄인 정의보다 느슨하다. 공식 객체는 모두 통과하고, 정의에 없는 속성·잘못된 타입·enum·
  필수 누락·제약 위반만 실패한다. 우리 코드가 내보내는 값은 알럿 회귀 테스트(`tests/normalize/`)가 지킨다.
- 매핑표(`../mapping_tables/*.yaml`)의 target은 이 정의로 검사한다(`table_check.py`, D-061).

## 줄여 둔 클래스(#234)

`classes/4002.json`(http_activity), `classes/6003.json`(api_activity)은 Event 정규화가 쓰는 줄인 정의다.
속성마다 `type`, `requirement`, `object_type`, `is_array`, `enum` 목록(값)만 남겼고 설명은 없다.
받은 곳은 `https://schema.ocsf.io/api/1.9.0/classes/<이름>?profiles=`다. 이 클래스들이 참조하는 객체는
위 `objects.json`에 들어 있고, 이전에 줄여 담았던 18개 객체와 `requirement`·`type`·`is_array`·`object_type`·
enum 값이 같음을 확인했다(2026-11-18). 로더는 두 형식을 같은 키로 읽는다.

## 이전에 확인한 것(그대로 유효)

- 목적지 IP 증거 객체: `https://schema.ocsf.io/api/1.9.0/objects/evidences?profiles=`
  (2026-11-12 확인). Detection Finding의 `evidences[].dst_endpoint`에 사용한다.
- Base Event는 `dst_endpoint`·`evidences`를 허용하지 않아 목적지 IP만
  `unmapped.destination.ip`에 보존한다. `unmapped`의 `object_type: object`는
  `https://schema.ocsf.io/api/1.9.0/objects/object?profiles=`의 generic object 정의
  (2026-11-12 확인)를 따른다. 이 객체에만 문자열 키와 JSON 값(유한 실수 포함)을
  재귀로 허용하고, 이름 있는 객체와 클래스 최상위 속성은 기존 정의로 엄격히 검사한다.
