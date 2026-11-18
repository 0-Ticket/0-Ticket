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
  - `https://schema.ocsf.io/api/1.9.0/classes/<이름>?profiles=`로 `CLASSES`의 클래스(처음에는 `base_event`,
    `detection_finding`)를 받고,
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

## 이벤트 클래스 확대(#340, 2026-11-19)

이벤트 수집 설정의 `class`(D-065)가 쓸 수 있는 클래스를 위 방법으로 더 받아 고정했다. 설정은 `classes/<번호>.json`이
있는 번호만 허용하고 2004는 이벤트 대상에 쓰지 못한다.

- 새로 받은 클래스: `2003`(compliance_finding), `3002`(authentication), `4001`(network_activity),
  `4003`(dns_activity). 예전에 줄여 두었던 `4002`(http_activity), `6003`(api_activity)은 공식 정의로 대체했다.
  이제 `classes/`의 8개(`0`, `2003`, `2004`, `3002`, `4001`, `4002`, `4003`, `6003`)가 모두 같은 형식이다.
- `objects.json`은 127개에서 138개가 됐다. 늘어난 11개(`assessment`, `authentication_token`, `check`, `compliance`,
  `dns_answer`, `dns_resource_record`, `dns_section`, `http_cookie`, `network_traffic`, `packet`, `tsig`)만
  더해졌고, 기존 127개는 바뀌지 않았다.
- 어떤 클래스를 받을지는 `scripts/fetch_ocsf_schema.py`의 `CLASSES`가 정한다. 클래스를 더할 때는 거기에
  이름과 번호를 더하고 스크립트를 다시 실행한다.
- 클래스를 받아 두는 것과 정규화가 그 클래스를 쓰는 것은 다르다. 이벤트 매핑표(`mapping_tables/events/<번호>.yaml`)는
  후속 이슈에서 만든다.

## 이전에 확인한 것(그대로 유효)

- 목적지 IP 증거 객체: `https://schema.ocsf.io/api/1.9.0/objects/evidences?profiles=`
  (2026-11-12 확인). Detection Finding의 `evidences[].dst_endpoint`에 사용한다.
- Base Event는 `dst_endpoint`·`evidences`를 허용하지 않아 목적지 IP만
  `unmapped.destination.ip`에 보존한다. `unmapped`의 `object_type: object`는
  `https://schema.ocsf.io/api/1.9.0/objects/object?profiles=`의 generic object 정의
  (2026-11-12 확인)를 따른다. 이 객체에만 문자열 키와 JSON 값(유한 실수 포함)을
  재귀로 허용하고, 이름 있는 객체와 클래스 최상위 속성은 기존 정의로 엄격히 검사한다.
