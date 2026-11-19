---
issue: 349
date: 2026-11-20
owner: uptime-zero
supersedes: []
---

# 이벤트 매핑표: nginx(ECS 층)와 ModSecurity(소스별 층)를 mapping_tables/events/ 표로 옮긴다

## 목표

이벤트의 필드 읽기를 코드(`_web_event`)에서 `mapping_tables/events/` 표로 옮긴다. 대상은 nginx 접근 로그와 ModSecurity 감사 로그의 요청·응답·엔드포인트이며 둘 다 HTTP Activity(4002)다. 클래스는 소스 표의 `detect`로 정한다. 이벤트 `outcome`·`partial`은 이번에 만들지 않는다.

## 방법

1. **샘플과 테스트 먼저.** `tests/fixtures/normalize/events/`에 손으로 줄인 샘플(nginx, ModSecurity)을 만든다. 실제 `_source`를 본 구조를 따르되 IP는 문서용 대역(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`), 도메인은 `example.com`, 지리·AS·ID·계정은 가짜 값을 쓴다. ModSecurity 샘플에는 응답 본문·룰 매치·헤더 전체를 넣지 않는다. 기존 `raw.json`의 웹 샘플(nginx·apache)은 회귀 기준으로 둔다.
2. **표 파일 구성.** `mapping_tables/events/` 안에 두 종류를 둔다. 알럿 표 로더(`tables.py`, `mapping_tables/*.yaml` 비재귀)는 이 폴더를 계속 읽지 않는다.
   - `events/<클래스 번호>.yaml`(예 `4002.yaml`): 클래스 공통 ECS 층. 기존 `class_uid`·`summary`에 `entries`·`entities`를 더한다.
   - `events/<소스 이름>.yaml`(예 `nginx.yaml`, `modsecurity.yaml`): 소스별 층. `class_uid`, `detect`, `entries`, `entities`를 가진다. 파일 이름(소스 이름)이 이후 이벤트 `outcome`의 `source` 값이 된다. 파일 이름이 숫자면 클래스 표, 아니면 소스 표다.
   - 소스 표의 `entries`는 클래스 표의 같은 target을 덮어쓰고, 소스 표의 `entities`는 클래스 표 엔티티 뒤에 쌓는다(알럿 표의 D-064와 같은 규칙).
3. **로더.** `event_tables`가 두 종류를 읽는다. 클래스 표는 `entries`·`entities`를 `tables.Table`로 해석하는 `parse_table`을 재사용하고, 소스 표는 `class_uid`와 `detect`를 더 읽는다. 알 수 없는 키, 클래스 정의가 없는 `class_uid`(`EVENT_CLASSES` 밖), 소스 표의 `class_uid`에 해당하는 클래스 표가 없음은 `MappingTableError`다. `detect`는 알럿과 같은 문법(`field`, `equals`·`exists`)이다.
4. **클래스 결정(D-069).** 이벤트(`kind = event`)의 클래스는 다음 순서로 정한다: 설정 `class`(D-067, 이번에는 정규화에 연결하지 않음) → 소스 표의 `detect`가 맞는 첫 표(표 이름 순)의 `class_uid` → 기존 인덱스 정규식(`logs-nginx.access-*` 등 → 4002, 클라우드 → 6003) → Base Event(0). `.ds-filebeat-…` 인덱스라도 `event.module`이 `nginx`·`modsecurity`면 4002가 된다.
5. **4002 매핑.** `_web_event`를 표 적용으로 바꾼다. 클래스 표 → 소스 표 순으로 `apply_table`을 부르고 `_nested`로 OCSF 객체를 만든다.
   - 코드가 채우는 것: `class_uid`, `category_uid`, `activity_id`, `type_uid`, `severity_id`, `metadata.version`·`product`, `message`(요약).
   - `activity_id`·`activity_name`: 표가 `activity_name`(원본 메서드, 대문자)과 `http_request.http_method`(목록에 있는 메서드만)를 낸다. 코드는 `http_method`가 있으면 `HTTP_ACTIVITY_IDS`로 `activity_id`를 정하고 `activity_name`을 버리고, 없고 `activity_name`만 있으면 `activity_id = 99`와 `activity_name`을 두고, 둘 다 없으면 `activity_id = 0`이다(#347 규칙 그대로).
   - `metadata`는 코드 값과 표 값(`correlation_uid`, `original_time`)을 병합한다(`_ocsf`가 `metadata`를 통째로 덮어쓰지 않게).
   - 요약(`message`)은 #347 규칙 그대로다(클래스 표의 `summary` → `event.dataset` → `event`).
   - 6003(클라우드)과 Base Event(0)의 매핑·엔티티(`_cloud_event`, `_base_event`, `ENTITY_FIELDS`)는 이번에 바꾸지 않는다. 이들은 `host.name`을 계속 읽는다.
6. **새 변환**(변환 등록부, 표에 스크립트를 넣지 않는다, D-061): `http_method`(목록에 있는 메서드만, 대문자), `method_name`(대문자 문자열), `to_int`(정수 또는 ASCII 숫자만 든 짧은 문자열. bool·비ASCII 숫자·긴 문자열은 버림. 현재 `_integer`와 같은 동작), `geo_coordinates`(`{lat, lon}` 객체 → `[경도, 위도]`, 유한한 수만), `ctime_utc`(`"Thu Nov 19 15:49:58 2026"` → UTC 밀리초. 요일·월 이름은 로캘에 의존하지 않고 직접 읽고, 한 자리 날짜의 공백 두 칸을 허용). 객체·정수를 받는 변환을 위해 `accepts`를 쓴다.
7. **값을 읽지 못할 때.** `apply_table`이 `errors`에 올린 속성은 그 속성만 비운다(현재 `_integer` 동작). 다만 `time`은 값이 있는데 읽을 수 없으면 정규화를 `validation_failed`로 실패시킨다. `time`을 읽을 값이 하나도 없어도 같다. `errors`·`missing`은 이번에 저장하지 않는다(이벤트 `outcome`은 후속).
8. **시각.** 클래스 표의 `time`은 `@timestamp`다. `modsecurity.yaml`은 `time`을 `transaction.time_stamp`(`ctime_utc`)에서 읽고 `@timestamp`를 다음 경로로 둔다(필드가 없을 때만). 원문 문자열은 `metadata.original_time`에 보존한다. `time_stamp`의 시간대는 문서로 확인하지 못해서 UTC로 간주한다(같은 요청의 nginx 로그 `+0000`과 시각이 같음을 샘플로 확인). 서버가 UTC가 아니면 틀릴 수 있다는 점을 기록에 남긴다.
9. **엔티티.** 4002 표는 센서 값(`host.name`, `agent.*`)을 읽지 않는다. 클래스 표는 알럿 공통 표와 같은 type·role로 `source.ip`(src), `destination.ip`(dst), `user.name`(actor), `url.domain`(dst, `domain_or_ip`), `destination.domain`(dst, `domain_or_ip`), `url.original`(dst, 변환 없음)을 읽는다. 지금 이벤트는 `domain`·`url`의 role이 `None`인데 `dst`로 바뀐다. `modsecurity.yaml`은 `transaction.host_ip`(dst ip), `transaction.request.hostname`(dst, `domain_or_ip`)을 더한다.
10. **ECS 허용 목록과 표 검사.**
    - `src/soc/normalize/ecs_fields.yaml`: 우리가 읽는 ECS 필드 이름, 타입, 배열 여부. 클래스 표(`events/<클래스 번호>.yaml`)의 `entries`·`entities`의 `from` 경로가 이 목록 안에 있는지 pytest가 검사한다. 소스 표(`transaction.*` 등)는 대상이 아니다. 목록의 이름은 ECS 문서로 대조한다.
    - 표 검사: 이벤트용 검사 함수가 target이 클래스 정의에 있는지, 변환이 내보낼 값이 target enum 안인지, 클래스 표 + 소스 표로 클래스의 필수 속성이 채워지는지를 본다(`table_check`의 2004 전용 상수를 이벤트용으로 나눔: 이벤트의 코드 채움 경로에는 `time`이 없다). `at_least_one(http_request, http_response)`는 `validate_ocsf`와 샘플 테스트가 본다.
11. **ModSecurity 읽기 범위.** 읽는 것: `source.ip`(클래스 표), `transaction.client_port`, `host_ip`, `host_port`, `request.{method,http_version,uri,hostname}`, `request.headers.User-Agent`, `response.http_code`, `response.headers.Content-Length`·`Content-Type`(대소문자 두 표기), `unique_id`, `time_stamp`. 읽지 않는 것: `response.body`, 헤더 객체 전체, `messages`(룰 매치), `is_interrupted`(차단 여부).
12. **기록.** `docs/notes/349-event-mapping-tables.md`에 샘플에서 확인한 사실, UTC 가정의 한계, 이후 이슈의 입력(Suricata·CloudTrail 후속 결정, 6003·Base의 `host.name` 엔티티가 남아 있음)을 적는다. 이 PR이 머지되면 `reprocess --kind event`로 기존 이벤트가 다시 분류된다.

## 바꿀 곳

- `src/soc/normalize/mapping_tables/events/4002.yaml`: `entries`·`entities` 추가
- `src/soc/normalize/mapping_tables/events/nginx.yaml`, `modsecurity.yaml`(새 파일)
- `src/soc/normalize/event_tables.py`: 소스 표 읽기, 표 적용 함수, 클래스 결정 보조
- `src/soc/normalize/mapping.py`: `normalize()`의 이벤트 클래스 결정, `_web_event`를 표 적용으로 교체, `metadata` 병합
- `src/soc/normalize/transforms.py`: 새 변환 5개와 `accepts`
- `src/soc/normalize/table_check.py`: 이벤트용 표 검사(2004 전용 상수 분리)
- `src/soc/normalize/ecs_fields.yaml`(새 파일)
- `tests/normalize/`: 표 로더, 클래스 결정, 변환, 표 검사, 허용 목록, nginx·ModSecurity 샘플 테스트, `raw.json` 웹 샘플의 엔티티 기대값 갱신
- `tests/fixtures/normalize/events/`: 손으로 줄인 샘플
- `docs/decisions.md`(D-069), `docs/plans/349-event-mapping-tables.md`, 개발 중 `docs/notes/349-event-mapping-tables.md`

## 다른 코드와 맞물리는 곳

- **엔티티 출력(L2·자산 조회):** 4002 이벤트에서 센서 `host`(Filebeat 컨테이너 ID)가 빠지고 `domain`·`url`의 role이 `None`에서 `dst`로 바뀐다. L2 그래프는 `src` role만 쓰고 자산 조회는 `(type, value)`로 조회해서 영향은 작지만 값이 바뀐다. L2 담당 확인(PR 전).
- **`events.ocsf`의 모양:** 4002 이벤트에 지리·AS·`http_response.length`·`http_request.version`·`metadata.correlation_uid`·`metadata.original_time`이 더해진다. `ocsf`를 읽는 L2·L3·UI 담당 확인(PR 전).
- **기존 이벤트의 클래스:** `.ds-filebeat-…`로 들어와 Base Event가 된 nginx·ModSecurity 이벤트가 `reprocess --kind event` 뒤 4002가 된다. `query_http_flow` 같은 4002 전용 도구(`tools/web.py`)가 그 이벤트를 읽게 된다. 개발 DB 사본에서 건수는 사람이 확인한다.
- **알럿 담당:** 이벤트에 `metadata.correlation_uid = transaction.unique_id`가 생긴다. 알럿 쪽에 같은 요청 ID가 있는지는 알럿 담당 확인(PR 전).
- **설정 키:** 없음. **DB:** 변경 없음(마이그레이션 `0304`의 CHECK가 4002와 0을 이미 허용한다).

## 범위 밖

- 이벤트 `outcome`·`partial`·`fallback`, 마이그레이션, `reprocess`의 `_one`/`_one_event` 합치기, `report` 변경
- 설정 `class`를 `raw_records`에 저장하고 정규화에 연결하는 일(DB 스키마 개편 결정 뒤 별도 이슈)
- ModSecurity 룰 매치·차단 여부·응답 본문·헤더 객체, 알럿과 이벤트를 잇는 `raw_links` 채우기
- 6003(클라우드)·Base Event 표와 엔티티 정리, Suricata, CloudTrail, apache(실제 샘플 없음), GuardDuty, Azure, GCP, Prowler
- 알럿 `common.yaml`·알럿 코드 변경

## 완료 기준

- [ ] nginx 샘플이 이전과 같은 값(메서드, 경로, 응답 코드, User-Agent)을 내고, 정의에 있는 지리·AS·응답 길이·HTTP 버전이 값이 있을 때만 채워진다(국가·지역은 ISO 코드, 좌표는 `[경도, 위도]`).
- [ ] ModSecurity 샘플이 4002로 만들어져 `validate_ocsf`를 통과한다(`src_endpoint`, `dst_endpoint`, `http_request`, `http_response`, `metadata.correlation_uid`, `metadata.original_time`).
- [ ] `time`이 nginx는 `@timestamp`, ModSecurity는 `transaction.time_stamp`(UTC 간주)에서 오고, `time_stamp`가 있는데 읽을 수 없으면 정규화가 `validation_failed`로 실패하며 필드가 없으면 `@timestamp`를 쓴다.
- [ ] 소스 표의 `detect`로 클래스가 정해진다: `.ds-filebeat-…` 인덱스의 nginx·ModSecurity 문서가 4002가 되고, 맞는 표가 없는 문서는 인덱스 정규식(또는 Base Event)으로 정해진다.
- [ ] `host.name`, `agent.*`는 4002 엔티티가 되지 않고, 응답 본문·헤더 객체·룰 매치는 `ocsf`에 들어가지 않는다.
- [ ] 표의 target과 필수 속성을 pytest가 검사한다. ECS 층 표가 허용 목록 밖의 필드를 읽으면 검사가 실패한다. 알럿 표 검사는 그대로 통과한다.
- [ ] 새 변환(`http_method`, `method_name`, `to_int`, `geo_coordinates`, `ctime_utc`)의 단위 테스트(`to_int`는 `raw.json`의 `web_status_code_*` 샘플과 같은 결과).
- [ ] `activity_id = 99` 처리와 `at_least_one(http_request, http_response)` 위반(스키마 실패) 동작이 이전과 같다.
- [ ] `reprocess --kind event`로 기존 이벤트가 새 표 결과로 갱신된다(개발 DB 사본 건수 확인은 사람이 한다).
- [ ] 엔티티 변화에 대한 L2 담당 확인, `ocsf` 모양 변화에 대한 L3·UI 담당 확인, `metadata.correlation_uid`에 대한 알럿 담당 확인(PR 전).
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과한다.

## 토론으로 정한 것

- **범위:** 원래 이슈대로 nginx(ECS 층)와 ModSecurity(소스별 층). 실제 `_source`가 있는 CloudTrail·Suricata 샘플은 남은 결정(서비스 호출의 출발지, 계정 ID 보존, flow 시각·방향·응용 프로토콜, `alert` 문서의 알럿 여부, 이벤트 종류별 클래스 구분)이 있어 후속 이슈로 한다.
- **표 파일 구성:** 이슈 본문은 소스별 표를 `events/`에 둔다고만 했다. 4002에 소스가 둘 이상이고 로더가 파일 이름을 클래스 번호로 제한하고 있어, 숫자 파일은 클래스 공통 ECS 층, 이름 파일은 소스 층으로 나눈다(알럿의 `common.yaml` + `<소스>.yaml` 구조와 같다).
- **클래스 결정(이슈 본문과 다름):** 이슈 본문은 클래스를 지금처럼 인덱스로 정한다고 했다. 인덱스로는 Filebeat 기본 스트림(`.ds-filebeat-…`)의 로그를 구분할 수 없고 설정 `class` 하나로는 섞인 스트림에 쓸 수 없어(잘못 매핑됨), 표의 `detect`(`event.module`)로 클래스를 정한다. 설정 `class`가 연결되면 "그 클래스의 표만 후보로 삼는다"는 제약으로 더한다. D-069가 D-067을 보완한다.
- **이벤트 `outcome`·`partial`:** 이번에 만들지 않는다. 나중에 마이그레이션할 때 영향이 적도록 정했다. `time`을 읽을 수 없으면 조용히 `@timestamp`로 대체하지 않고 실패시킨다(표시 없이 잘못된 시각이 저장되면 나중에 가려낼 수 없다. 실패한 원본은 `outcome` 도입 뒤 다시 정규화하면 된다). 다른 속성은 그 속성만 비우고, 원본이 `raw_records`에 있어 `reprocess`로 다시 읽을 수 있다. DB 변경은 없고 소스 표의 파일 이름이 이후 `source` 값이 된다.
- **엔티티:** 센서 값 제외, 나머지는 알럿 공통 표와 같은 기준(URL 규칙도 같음). 이 때문에 `domain`·`url`의 role이 `dst`로 바뀐다.
- **시각:** OCSF `time` 정의(활동이 소스에서 실제로 발생한 때)를 따른다. ModSecurity는 `@timestamp`가 Filebeat가 읽은 시각이라 `transaction.time_stamp`를 쓴다.
- **연관 ID:** `transaction.unique_id`를 `metadata.correlation_uid`에 넣는다(OCSF가 정한 연관 ID 자리). 알럿 쪽 쓸모는 알럿 샘플로 확인이 필요하다.
- **ECS 허용 목록:** ECS 정의를 통째로 고정하지 않고, 우리가 읽는 필드(수십 개)만 `ecs_fields.yaml`에 두고 클래스 표(ECS 층)만 검사한다.
- **apache:** 범위에는 없지만 클래스 표가 같은 4002라서 apache 문서에도 적용된다. 기존 `raw.json`의 apache 샘플이 회귀를 지키고 실제 apache 샘플은 없다.

## 바뀐 점
