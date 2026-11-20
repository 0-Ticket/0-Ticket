# 결정 목록

팀이 정한 도구와 방식이다. "확정"인 것만 코드에 들어간다. 이 목록은 2026-11-03, PR #191부터 쓴다. 번호가 #191보다 작은 이슈·PR에 적힌 결정 번호는 이 목록과 관계없다.

## 상태

| 상태 | 뜻 |
|---|---|
| 확정 | 팀이 정했다. 코드에 쓴다 |
| 후보 | 유력하지만 팀이 아직 의논하지 않았다. 쓰려면 계획 이슈에서 확정한다 |
| 담당자가 정함 | 그 부분을 구현하는 담당자가 계획 이슈에서 정한다. 예시는 참고용이다 |
| 추후 | 지금은 만들지 않는다 |
| 폐기 | 쓰지 않기로 했다 |

## 쓰는 법

- 정할 것이 생기면 계획 이슈의 "어떻게"에 적는다. `/soc-plan`이 확정되지 않은 도구나 방식을 발견하면 안건으로 올린다.
- 사람이 정하면 이 문서의 해당 행을 "확정"으로 옮기고 맨 아래 "기록"에 한 줄을 남긴다. 상태는 사람만 정하고, 사람이 정한 것을 AI가 받아 적는 것은 괜찮다.
- 결정을 바꾸면 같은 ID의 내용을 고치고 기록에 남긴다. 번호는 다시 쓰지 않는다.
- 다른 문서에서 결정을 가리킬 때는 `PostgreSQL(D-012)`처럼 설명을 먼저 쓰고 괄호에 ID를 쓴다. ID만 쓰지 않는다.

## 확정

### 기반

| ID | 결정 | 메모 |
|---|---|---|
| D-001 | 백엔드는 Python 3.13 + uv. 린트·포맷 ruff, 테스트 pytest | CI와 같은 명령 |
| D-002 | 설정 파일은 TOML. 기본 설정 위에 조직 설정 파일을 덮어쓴다 | 비밀 값은 넣지 않고 환경변수 이름만 적는다. 조직 설정 파일은 `config/local.toml`처럼 `config/local.*` 이름을 쓰고 커밋하지 않는다 |
| D-003 | 데이터 계약의 원본은 JSON Schema. Python(Pydantic)·TypeScript 코드는 생성하고, 생성 코드는 직접 고치지 않는다 | 계약 원본은 `contracts/`(JSON Schema draft-07). Python은 datamodel-code-generator로 `src/soc/contracts/generated/`에 생성한다. TypeScript는 json-schema-to-typescript로 contracts/에서 생성한다. API 전용 포장 타입은 응답 모델이 내보내는 JSON Schema에서 같은 도구로 생성한다(#266). 생성은 `scripts/generate_contracts.py`, CI는 `--check`로 차이를 검사한다 |
| D-004 | 라이선스는 Apache-2.0 | |
| D-039 | HTTP 클라이언트는 httpx(`httpx==0.28.1`). 리다이렉트는 따라가지 않는다 | 응답 크기 상한은 스트리밍하면서 압축을 푼 바이트로 세고, 요청 단위 timeout과 별도로 출처별 전체 마감 시간을 둔다. openai 3.x가 끌어오는 `httpx2`와 따로 설치된다. httpx는 2024-12 이후 릴리스가 없어, 보안 수정이 필요한데 나오지 않으면 다시 논의한다(#221) |
| D-041 | SSH 라이브러리는 asyncssh(`asyncssh==2.24.1`) | 라이선스는 EPL-2.0 OR GPL-2.0-or-later이고, 수정 없이 import만 한다. 버전은 고정하고 함께 들어오는 패키지는 `uv.lock`으로 고정한다(#213) |

### 수집 · 정규화

| ID | 결정 | 메모 |
|---|---|---|
| D-005 | 외부 SIEM 하나에 설정으로 연결만 한다. 여러 SIEM을 동시에 연결하지 않고, 연결 정보를 프로필로 두어 쉽게 바꿀 수 있게 한다 | SIEM 구축·운영은 범위 밖 |
| D-006 | 처음 연결할 SIEM은 ELK | 다른 SIEM은 필요해질 때 |
| D-007 | 알럿·이벤트 정규화 형식은 OCSF 1.9.0, 라이브러리 없이 직접 구현 | SIEM이 바뀌어도 같은 형태로 다룬다. 정규화 결과의 OCSF 객체는 OCSF 서버의 1.9.0 클래스·객체 정의로 검증한다. 클래스별 공식 JSON Schema 파일을 두도록 한 기존 검증 방식은 #234에서 바꿨다 |
| D-008 | SIEM에서 가져온 원본 Alert·Event는 바꾸지 않고 보관하며, 정규화 결과는 별도 테이블에 둔다 | 보관 기간은 설정 값 |
| D-049 | `raw_records` 원본은 `text`(JSON 글자, `original_text`)로 보관한다. 이스케이프는 `json.dumps(..., ensure_ascii=True)`다. 정규화 결과의 NUL·짝 없는 서로게이트는 `\u0000`·`\udXXX` 6글자로 치환한다(문자열 값과 dict 키 모두, `_normalize_and_save`에서) | jsonb는 `\u0000`을 받지 않아 NUL 문서 하나가 페이지 저장을 실패시켰다(#277). 원본은 `json.loads`로 SIEM이 준 JSON 그대로 되살린다(D-008). `CHECK (left(original_text, 1) = '{')`. `siem_ref`는 `<_index>/<_id>`를 JSON 문자열 이스케이프한 값(따옴표 제외)이다. 마이그레이션 `0106`은 빈 `raw_records`에서만 적용된다 |
| D-050 | 저장할 수 없는 hit는 `ingest_quarantine`에 원문과 이유를 격리한다. 페이지 단위 트랜잭션에서 RawRecord·격리 행·체크포인트를 저장한다. 격리 키는 모든 격리 hit에 위치 토큰과 안정 hit 해시를 넣으며, Base64url 페이로드가 128자를 넘으면 `h`와 해당 JSON 바이트의 SHA-256 hex로 축약한다. 완전히 같은 키는 한 행으로 병합한다. 일시 오류 요청마다 최대 3회, 정렬 값 문제 페이지 재조회마다 최대 3회로 별도 계산한다. 재시도 사이에는 1초 대기한다. `ingest_run`은 신규 격리 수를 기록한다 | NaN·±Infinity와 깊이 100 초과도 격리한다. NUL·짝 없는 서로게이트는 D-049에 따라 보존한다. 전체 원문은 `original_text`에 남긴다. 마지막 hit의 정렬 값 문제가 지속되면 페이지 행은 커밋하고 체크포인트는 유지한 채 실패한다. D-008 보관 설정·삭제와 운영자 알림·복구는 후속 이슈다(#294) |
| D-057 | 수동 수집 `soc.ingest`는 체크포인트가 없으면 `--since` 또는 `[ingest] initial_lookback_seconds`(기본 86400)부터 가져온다. 체크포인트가 있으면 `min(--since, 체크포인트 − overlap_seconds)`(기본 60초)부터 다시 읽고 중복은 `(siem_profile, siem_ref)`로 건너뛴다. 체크포인트는 후퇴하지 않는다(`store.save_page`가 저장된 `time_ms`보다 클 때만 갱신). 수집 명령은 DB advisory lock으로 동시에 하나만 돌고, 잠금을 못 잡으면 종료 코드 3이다. 인증서 검증 실패는 실패 종류 `tls`로 `network`와 구분한다 | 페이지 단위 저장·실패 시 커밋된 페이지까지 체크포인트 유지(D-050)는 그대로다. `--since`는 상대 값(`30m`·`24h`·`7d`)과 시간대 있는 ISO 8601만 받고 틀리면 종료 코드 2다. 요약의 가져온 건수·건너뜀 건수는 DB에 저장하지 않는다. 겹침 구간보다 늦게 색인되는 문서는 놓칠 수 있고, 커서 필드를 `event.ingested`로 바꾸는 것은 실제 ELK 확인 후 별도 이슈다(#317) |
| D-059 | Alert 정규화 뼈대 규칙. `time`·`finding_info.created_time`은 `kibana.alert.start`(없으면 `@timestamp`)이고, `start_time`·`end_time`과 Alert 계약의 `time`은 `kibana.alert.original_time`(없거나 읽을 수 없으면 `time`)이다. `rule_id`는 `kibana.alert.rule.rule_id`(없으면 null)이고 `finding_info.uid`는 `kibana.alert.uuid`, 없으면 hit `_id`다. 엔티티 role: ip·domain·url은 네트워크 방향대로 `src`·`dst`(`source.ip` src, `destination.ip` dst, `url.domain`·`destination.domain`·`url.original` dst. domain 값이 IP 형식이면 type은 `ip`), user는 `actor`, host는 `target`, file_hash·process는 행위자가 분명할 때만 `actor`이고 아니면 null이다. `host.name`·`agent.*`(수집기)는 엔티티로 만들지 않는다. Kibana 알럿으로 해석할 수 없으면(`_source` 없음·비객체, uid·룰 이름·생성 시각 없음, 매핑 결과의 OCSF·계약 검증 실패) class 0 폴백 Alert를 남기고, 알 수 없는 소스나 `rule_id`·`severity`·`original_time` 누락은 2004 + `partial`이다. 결과 품질은 `normalize_status.outcome`(`ok`·`partial`·`fallback`, 기존·Event 행은 NULL)·`missing_fields`(OCSF 경로)·`source`·`error_code`에 기록한다. 정규화 결과(`ocsf`·`details`)의 Cookie·Set-Cookie·Authorization 헤더 값은 마스킹한다. Alert 계약의 `ocsf.class_uid`는 2004 또는 0이다 | 시각을 두 개로 나누는 것은 OCSF가 finding의 `time`을 생성 시각으로 정하기 때문이다. 폴백은 증적용 알럿이 Ticket 없이 사라지지 않게 한다. 일시 오류(DB·자산 조회)와 Event 실패는 `failed` + 재시도다. 마스킹은 `raw_records.original_text`를 바꾸지 않고, 에이전트의 원본 조회 도구에는 적용하지 않는다(별도 안건 후보). JSON 손상 원본의 폴백은 D-050 알려진 한계로 남는다. 소스별 매퍼가 host(target) 등을 채운다. Alert 계약 변경은 L1·L2·L3 담당자 승인이 필요하다(#326) |
| D-060 | 소스별 매핑표는 YAML 파일이고 PyYAML을 직접 의존으로 쓰며 `yaml.safe_load`만 부른다. 표에는 조건식·스크립트를 넣지 않는다(#328) | 소스·도구를 더할 때 정규화 코드를 고치지 않고 표만 더하기 위해서다. PyYAML은 이미 간접 의존으로 설치돼 있어 추가 비용이 작고, `safe_load`는 임의 객체 생성을 막는다 |
| D-061 | 선언형 매핑표 규칙. 항목은 `target`·`from`·`transform`·`required`이고 `from`은 `_source` 기준 점 표기(평면 점 키·중첩 모두, `_source` 밖은 `$.`로 시작)로 앞에서부터 처음 있는 값을 쓴다. `transform`은 코드에 등록된 변환 이름만 쓰고 모르는 이름은 표 로드 시점(정규화 실행기 시작)에 오류다. 표 `required` 누락은 `partial` + `missing_fields`이고, 폴백 조건(uid·title·생성 시각)·`_detect_source`·상수·시각 분리·엔티티·`evidences`·`attacks`·`observables`·`metadata`는 코드에 둔다. `detect`는 필드 equals 값 또는 키 존재 형식으로 위에서부터 첫 일치다. OCSF 정의는 클래스 0·2004와 참조 객체 127개를 공식 API(`/api/1.9.0/classes\|objects/<이름>?profiles=`)에서 `object_type`을 따라 받아 `ocsf/`에 고정하고 직접 수정하지 않는다. 표는 `src/soc/normalize/` 아래에 둔다 | D-059 동작을 바꾸지 않고 규칙의 위치만 코드에서 표로 옮긴다. 공식 단일 컴파일본이 없어(`/export/schema`가 프로필 충돌로 400) API 순회로 만든다. 고정한 객체는 모두 공식 정의라 목록 밖 객체도 검사를 통과하지만, 우리 코드가 내보내는 값은 알럿 회귀 테스트로 지킨다. 계획은 `docs/plans/328-ocsf-schema-mapping-tables.md`. 엔티티·`_detect_source`를 코드에 둔다는 부분은 D-062가 대체한다. 고정하는 클래스는 D-067이 2003·3002·4001·4002·4003·6003까지 넓힌다 |
| D-062 | 매핑표에 `entities` 섹션을 둔다. 항목은 `type`·`role`(생략하면 null)·`from`·`transform`이고 `type`·`role`은 Alert 엔티티 계약의 허용 값이다. 엔티티 변환은 `entries` 변환과 분리된 등록부에 두고 `(type, 값)`을 돌려준다(`ip`, `domain_or_ip`: 포트·대괄호를 떼고 IP면 type을 `ip`로). ECS 표준 엔티티(`source.ip`·`destination.ip`·`user.name`·`url.domain`·`destination.domain`·`url.original`)는 `common.yaml`에, 소스 표는 더할 것만 둔다. 적용은 common → 소스 표 순이고 같은 엔티티는 한 번만 둔다. type이 ip인 값이 IP가 아니면 role에서 누락 경로를 만든다(src → `evidences[].src_endpoint.ip`, dst → `evidences[].dst_endpoint.ip`). `detect` 조건의 `field`는 문자열 또는 목록(앞에서부터 처음 있는 값)이다. ModSecurity·Suricata의 `detect`는 표에 두고 GuardDuty 판별만 코드에 남긴다. 순서는 표 → GuardDuty → unknown이다(#332) | D-059 role 규칙은 그대로이고 위치만 코드에서 표로 옮긴다. ModSecurity는 `transaction.client_ip`(src)·`host_ip`(dst)·`request.hostname`(dst)을 더해 목적지를 복구한다. 실제 알럿 54건 모두에 이 필드가 있다. `evidences`는 코드가 `destination.ip`로 채우는 그대로다. ModSecurity에 dst 엔티티가 생겨 L1·L2·L3가 읽는 데이터가 바뀌지만 계약은 그대로이고 D-027의 그래프 연결은 `src`만 쓴다. 이미 정규화된 알럿은 바뀌지 않는다. 계획은 `docs/plans/332-modsecurity-suricata-mapping-tables.md` |
| D-063 | 알럿 재처리 명령 `python -m soc.normalize reprocess`는 `alerts`의 `time`·`severity`·`title`·`rule_id`·`entities`·`assets`·`ocsf`·`details`와 `normalize_status`의 `outcome`·`source`·`missing_fields`·`error_code`만 갱신한다. `id`·`raw_id`·`triage`와 `status`·`result_id`·`result_kind`는 바꾸지 않는다. 대상은 `result_id`가 가리키는 Alert 한 건이고, 기본은 `outcome`이 NULL인 행, `--source`를 주면 새 결과의 `source`가 같은 모든 행이다. 새 결과가 폴백·오류이거나 기존 `outcome`(ok > partial > fallback)보다 낮아지면 건너뛰고, 달라진 행만 행 단위 트랜잭션에서 `FOR UPDATE`로 잠가 갱신한다. 임베딩과 이미 만든 Incident·그래프 묶음은 다시 만들지 않는다(#334) | 재처리를 `run`으로 하면 알럿 id가 새로 생겨 L1 판정·Ticket이 중복된다. 임대 경로(`claim_*_batch`)는 Alert·Event를 구분하지 않아 쓰지 않는다. 기존이 더 나은 값은 덮어쓰지 않는다. 임베딩(`similar/index.py`, `l2/branch/embed.py`)은 옛 `title`·엔티티 기준일 수 있다. `alerts.raw_id` 유니크 제약과 중복 알럿 정리는 별도 이슈다. 계획은 `docs/plans/334-reprocess-alerts.md` |
| D-064 | 엔티티 항목에 선택 항목 `when: {field, equals}`를 둔다. `field`는 문자열 또는 목록(`detect`와 같은 문법), `equals`는 문자열 하나만 받고 `exists`는 받지 않는다. 필드 값이 없거나 다르면 그 항목을 적용하지 않는다. 로더가 알 수 없는 키·빠진 `field`·문자열이 아닌 `equals`를 `MappingTableError`로 막고 원본 필드 이름은 검증하지 않는다. 소스 표의 `entries`는 `common`의 같은 target을 덮어쓰고, 원본에 값이 없으면 `common` 값을 유지하며 새 `required`는 만들지 않는다. GuardDuty 판별을 `guardduty.yaml`의 `detect`(`guardduty` 키 존재)로 옮기고 코드의 판별을 없앤다. 소스 판별은 표 이름 순이고 순서는 표 → unknown이다(#336) | `when`은 D-060의 "조건식 금지"에서 equals 한 가지만 허용하는 예외다(`detect`가 이미 같은 문법을 쓴다). GuardDuty 네트워크 연결은 방향에 따라 src와 dst가 바뀌어 role 고정 선언으로 표현할 수 없다. 제목·설명은 원본의 `guardduty.title`·`description`에 있다. D-062의 "GuardDuty 판별만 코드에 남긴다"를 대체한다. OUTBOUND의 로컬 IP(피해 호스트 사설 IP)가 `src`가 되어 D-027의 그래프 연결 근거가 된다. 계정 ID는 `host`/`target`이라 Hostname observable이 되고 자산 조회가 `(host, 계정ID)`로 찾는다. 계획은 `docs/plans/336-guardduty-mapping-table.md` |
| D-065 | Alert 저장 구조. `alerts.ocsf`가 원본이고 순수 OCSF 1.9.0 문서(2004, 폴백은 0)다. `title`·`time`·`severity`·`rule_id` 컬럼은 `mapping.py`의 파생 함수 한 곳이 `ocsf`에서 만든다(`time` = `start_time`, 없으면 `time` / `title` = `finding_info.title`, 없으면 `message` / `rule_id` = `finding_info.analytic.uid`, 없으면 null / `severity` = `severity_id`이고 99는 0). 정규화·재처리·시드 3종이 모두 이 함수를 쓴다. `entities`가 분석용 원본이고 `observables`·`evidences`는 entities에서만 만든다. `evidences`는 엔티티 하나당 요소 하나이고 `ip`/`src`는 `src_endpoint.ip`, `ip`/`dst`는 `dst_endpoint.ip`, `user`/`actor`는 `actor.user.name`, `domain`/`dst`는 `dst_endpoint.domain`, `url`/`dst`는 `url.url_string`이다. role이 `target`·null이거나 대응이 없는 type은 `evidences`에서 빼고 `observables`와 entities에는 유지한다. `details`는 비OCSF 값만 두며 OCSF 속성 이름과 같은 키를 두지 않는다. `alerts`에 `class_uid IN (2004, 0)` CHECK를 더하고 `severity` CHECK(0~6)는 그대로다. 재처리 명령은 기존 행 전체를 대상으로 하는 옵션을 가진다(#338) | D-059의 시각·`rule_id` 규칙은 그대로다. D-062의 "`evidences`는 코드가 `destination.ip`로 채우는 그대로"를 대체하고, D-063의 갱신 컬럼 중 `title`·`time`·`severity`·`rule_id`·`ocsf`는 같은 파생 함수의 결과를 쓴다. 같은 값이 컬럼과 `ocsf`에 중복이라 원본이 불분명하고 쓰기 지점이 여러 곳이라 어긋날 수 있었다. 생성 컬럼은 시드·테스트 INSERT를 깨뜨려 쓰지 않는다. 현재 정규화는 알럿에서 `severity_id` 99를 만들지 않아 접는 규칙은 방어용이다. `alerts`를 비우고 새 id로 재수집하면 L1 판정·Ticket이 중복돼(D-063) 재처리로 대신한다. `ocsf` 안 `evidences`가 늘어 에이전트 도구가 보는 값이 바뀌며, 시드 픽스처·코드 변경과 함께 L1·L2·L3 담당자 확인을 받는다. 계획은 `docs/plans/338-alert-ocsf-source.md` |
| D-066 | Alert 계약 구조. Alert JSON의 최상위는 `alerts.ocsf` 컬럼의 OCSF 1.9.0 문서(2004, 폴백은 0)이고 `ocsf` 키는 없다. 우리 쪽 값 `id`·`raw_id`·`rule_id`·`entities`·`assets`·`triage`는 `details`에 두고, DB `details` 컬럼의 부가 값(`fallback` 등)과 합친다. 계약은 필수 키 `class_uid`·`time`·`severity_id`·`details`만 적고 나머지 OCSF 속성은 `additionalProperties: true`다. `class_uid`가 2004일 때만 `finding_info`를 필수로 둔다. `details` 필수 키는 위 6개이고 `rule_id`는 필수이되 `string \| null`이다(폴백은 null). `details`에는 OCSF 속성 이름과 같은 키를 두지 않는다. 행 → Alert JSON 조립은 DB 없는 순수 읽기 함수 한 곳이고 `ocsf`를 변환 없이 쓴다. OCSF 검증은 `details`를 뺀 문서에, 계약 검증은 전체에 적용한다. JSON에서 `time`·`severity`는 헬퍼 `alert_time`(`start_time`, 없으면 `time`)·`alert_severity`(`severity_id`, 99는 0)로 읽고 SQL은 컬럼을 쓴다. `ToolSpec.id_fields`는 점 경로(`details.id`)를 받는다. DB 컬럼, L1·L2·L3가 모델에 주는 평면 입력, `query_records`·`get_event`는 바꾸지 않는다(#339) | D-059의 "Alert 계약의 `ocsf.class_uid`는 2004 또는 0이다"를 계약 구조 전체로 넓히고, D-065가 #338 범위로 미룬 "공통 계약과 읽는 쪽 코드"를 바꾼다. Alert 10개 필드와 OCSF 2004·0 최상위 속성을 대조해 겹치는 것은 `time`(OCSF는 생성 시각)과 `severity`(OCSF는 문자열 라벨) 둘뿐이다. `get_alert`와 `raw_detail`의 alert `record`는 조립 JSON을 돌려주고, 같은 알럿이 모델 입력(`task.data`)에서는 평면이다. 근거 ID `alt_…`는 같다. Event 계약과 마스킹 범위 재정의는 이번에 하지 않는다(후속 이슈). 공통 계약 변경이라 L1·L2·L3·UI 담당이 계획 확정 전에 승인했다. 계획은 `docs/plans/339-alert-ocsf-top-level.md` |
| D-067 | 이벤트 수집 대상(`[[ingest.sources]]`)의 OCSF 클래스는 선택 항목 `class`(클래스 번호, 정수)로 선언한다. 허용하는 번호는 `src/soc/normalize/ocsf/classes/`에 공식 정의 파일이 있는 클래스이고, 2004는 알럿 전용이라 이벤트 대상에 쓸 수 없으며 `kind = "alert"` 대상에는 `class`를 쓸 수 없다. 이 값들이 틀려도 수집을 멈추지 않는다. 클래스를 정할 수 없는 값(정수 아님, 2004, 정의 파일 없음)은 Base Event(class 0)로 두고, 알럿 대상의 `class`는 무시한다. 적지 않으면 `None`이며 지금처럼 `_index`로 고른다. 공식 정의는 `scripts/fetch_ocsf_schema.py`로 받고 2003·3002·4001·4002·4003·6003을 더해 optional 속성과 참조 객체까지 고정한다. `[[ingest.sources]]` 표에는 `kind`·`key`·`time_field`·`class`만 쓸 수 있고 그 밖의 키는 무시한다. 위의 경우 모두 조용히 사라지지 않게 stderr에 `경고:` 줄을 남기고 수집은 계속하며 종료 코드는 그대로다. `kind`·`key`·`time_field`가 없거나 형식이 틀린 경우만 수집이 불가능해 설정 오류다. 이 결정은 설정을 읽고 검사하는 데까지이고 정규화에는 연결하지 않는다. 이벤트 매핑표는 `mapping_tables/events/<클래스 번호>.yaml`에 둔다(#340) | 알럿과 이벤트의 구분을 `kind`로 설정이 정하는 것과 같은 이유다. SIEM마다 기준이 달라 설정이 선언하고 코드는 선언을 따른다. `event.category`는 한 값이 여러 클래스에 걸려 클래스를 정하는 데 쓰지 않는다. 받는 범위는 ModSecurity·Suricata·Nginx·GuardDuty·CloudTrail·Prowler에서 주로 나오는 클래스이고 필요해지면 `CLASSES`에 더한다. 별도 클래스 목록 파일은 `ocsf/classes/`와 겹쳐 두지 않는다. 예전에 줄여 둔 4002·6003 정의는 공식 정의로 대체한다. 원본에 클래스를 저장하는 일, 정규화 연결, 이벤트 매핑표 작성은 DB 스키마 개편 결정 뒤 후속 이슈다. 계획은 `docs/plans/340-event-class-config.md` |
| D-068 | Event 저장·계약 구조를 Alert(D-065·D-066)와 같게 한다. `events.ocsf`가 원본이고 OCSF 1.9.0 문서다. `time`(`start_time`, 없으면 `time`)·`summary`(`message`)·`ocsf_class`(`class_uid`) 컬럼은 파생 함수 한 곳이 `ocsf`에서 만들고 정규화·재처리·시드 3종이 모두 쓴다. 개별 이벤트의 `time`은 활동 발생 시각이고 `start_time`은 비운다. Event JSON의 최상위는 `ocsf` 컬럼의 OCSF 문서이고 `ocsf` 키는 없으며, 우리 쪽 값 `id`·`raw_id`·`entities`·`assets`는 `details`에 둔다(필수 키 `class_uid`·`time`·`severity_id`·`details`, `additionalProperties: true`, `details`에 OCSF 속성 이름 금지). `summary`는 `message`에서 파생하고 정규화가 `message`를 채운다(1순위 클래스별 요약, 2순위 `event.dataset`, 3순위 `event`). 클래스별 요약은 `mapping_tables/events/<클래스 번호>.yaml`의 `summary`에 OCSF 경로로 정의하고(저장한 7개 클래스 0·2003·3002·4001·4002·4003·6003) 경로는 `ocsf/classes/` 정의로 pytest가 검사하며 알럿 매핑표 로더는 이 폴더를 읽지 않는다. `activity_id = 99`이면 `activity_name`에 출처 고유 값을 담는다(Base Event·4002·6003 공통). `events`에는 `class_uid` 7개 CHECK를 둔다. `reprocess --kind event`로 기존 이벤트를 id 유지한 채 다시 만들고(`outcome` 비교는 후속) `--source`는 알럿에서만 쓴다. `get_event`와 `raw_detail`의 event `record`는 조립 JSON을 돌려주고 `get_event`의 `id_fields`는 `details.id`다. D-066의 "`get_event`는 바꾸지 않는다"를 대체한다. 클래스 연결, 이벤트 매핑표, 엔티티·`observables` 정리, 이벤트 `outcome`은 이번에 하지 않는다(후속). 공통 계약 변경이라 L1·L2·L3·UI 담당 확인이 PR 전에 필요하다. 계획은 `docs/plans/347-event-ocsf-top-level.md` |
| D-069 | 이벤트 매핑표의 구성과 클래스 결정. 표는 `mapping_tables/events/` 아래에 두 종류를 둔다. 파일 이름이 클래스 번호인 `<클래스 번호>.yaml`은 그 클래스 전체에 적용하는 ECS 층이고 `class_uid`·`summary`에 더해 `entries`·`entities`를 가진다. 소스 이름인 `<소스>.yaml`은 소스별 층이고 `class_uid`·`detect`·`entries`·`entities`를 가진다. 소스 표의 `entries`는 클래스 표의 같은 target을 덮어쓰고 `entities`는 뒤에 쌓는다(D-064와 같은 규칙). 알럿 표 로더는 이 폴더를 읽지 않는다. D-068의 표 위치 서술(`<클래스 번호>.yaml`만)을 이 구성으로 보완한다. 이벤트의 클래스는 설정 `class`(D-067, 정규화에는 아직 연결하지 않음) → 소스 표의 `detect`가 맞는 첫 표(표 이름 순)의 `class_uid` → 인덱스 정규식 → Base Event(0) 순서로 정한다. D-067의 "적지 않으면 인덱스로 고른다"를 "적지 않으면 표의 `detect`로, 그것도 안 맞으면 인덱스로"로 보완하고, 설정 `class`를 연결할 때는 그 클래스의 표만 후보로 삼는 제약으로 더한다. 클래스 표(ECS 층)는 ECS 필드를 읽고, 읽는 ECS 필드는 `src/soc/normalize/ecs_fields.yaml` 허용 목록 안에 있어야 하며 pytest가 검사한다. 소스 표의 모듈 전용·원본 구조 필드(`transaction.*` 등)는 허용 목록 대상이 아니다. 이벤트 `time`은 OCSF 정의대로 활동이 소스에서 발생한 시각이고 소스 표가 읽을 필드를 정한다. 시간대가 없는 값은 UTC로 간주하고 원문은 `metadata.original_time`에 보존하며, 값이 있는데 읽을 수 없으면 정규화를 `validation_failed`로 실패시킨다. 그 밖의 속성을 읽지 못하면 그 속성만 비운다. 이벤트 `outcome`·`partial` 기록은 후속이고 소스 표의 파일 이름이 이후 이벤트 `source` 값이 된다. 4002의 엔티티는 알럿 공통 표와 같은 기준이며 센서 값(`host.name`, `agent.*`)은 읽지 않는다. 6003·Base Event의 매핑·엔티티는 바꾸지 않는다. 공통 출력(엔티티 role과 `host`, `ocsf` 모양, 기존 이벤트의 클래스 변경)은 L2·L3·UI 담당과 알럿 담당 확인이 PR 전에 필요하다. 계획은 `docs/plans/349-event-mapping-tables.md` |

### 에이전트

| ID | 결정 | 메모 |
|---|---|---|
| D-009 | 기본 LLM은 Azure AI Foundry `gpt-oss-120b`(OpenAI 호환 v1 API, Chat Completions). 주소·모델(배포) 이름·키 환경변수 이름은 설정 값이라 코드를 고치지 않고 Groq·Ollama 같은 다른 OpenAI 호환 제공자로 바꿀 수 있다 | 실제 연결·구독·리전은 #224에서 확인했다(`docs/notes/224-l3-real-model.md`). Foundry는 도구 정의에 strict를 켜면 최종 답이 빈 문자열로 와서 `[llm] strict_mode` 기본값은 `false`다(#215) |
| D-010 | SIEM 조회 도구는 읽기 전용이다 | |
| D-011 | SSH 도구는 읽기 전용이다. 접속 대상·계정·허용 명령은 설정 값이고 기본은 비어 있어 전부 거부한다. 키는 환경변수로만 읽는다. 허용 단위는 인자까지 포함한 명령 템플릿이다. SSH는 원격 서버의 셸이 명령 문자열을 다시 해석하므로, 인자 자리에 들어가는 값은 허용 형식만 받고 셸 특수문자가 들어 있으면 거부한다. 인자 값이 `-`로 시작하면 거부한다. 옵션으로 해석돼 명령이 쓰기·삭제로 바뀌는 것을 막기 위해서다. 원격 접속 계정은 읽기 권한만 가진 계정을 쓴다. 문자열 검사가 뚫려도 쓰기가 되지 않게 하는 마지막 방어선이다 | 원격 셸 해석을 막는 구체 방법(#213): 모델은 설정에 이름을 붙인 호스트와 코드에 정해진 점검 이름만 고르고, 명령 본문과 인자 모양은 코드 상수다(설정은 호스트별로 켤 점검만 정한다). 인자는 허용 문자만 받는다. 정수는 범위만 보고, 경로는 `/`로 시작하고 `[A-Za-z0-9._/-]`만 쓰며 256자 이하이고 `..` 구간·연속 `/`·끝의 `/`는 받지 않는다. `-`로 시작하는 값은 모두 거부한다. 통과한 값도 정수까지 문자열로 바꿔 `shlex.quote`로 감싸 명령에 넣는다. 원격 `authorized_keys`의 `command=` 제한은 운영자가 더할 수 있는 두 번째 방어선이다(코드로 만들지 않는다) |
| D-022 | 에이전트 프레임워크는 OpenAI Agents SDK(`openai-agents==0.24.0`, `openai==3.42.1`). Chat Completions 경로(`OpenAIChatCompletionsModel`)로 붙이고, 에이전트를 실행하는 코드 진입점에서 `set_tracing_disabled(True)`로 트레이싱을 끈다 | 트레이싱은 기본으로 켜져 있고 모델 입력·출력을 OpenAI 서버로 보낸다(`docs/security.md`). 환경변수에 맡기지 않는다. 구조화 출력(`output_type`)과 병렬 도구 호출은 쓰지 않는다. 함께 들어오는 패키지는 `uv.lock`으로 고정한다 |
| D-023 | 에이전트 도구는 파이썬 함수 도구 레지스트리(`soc.tools`의 `ToolRegistry`·`ToolSpec`)로 만들고 Agents SDK 함수 도구(`FunctionTool`)로 감싼다. MCP 서버는 쓰지 않는다 | 도구는 단계별 허용 목록(`[tools.allowed]`)에 있는 것만 SDK에 등록한다. MCP 노출은 필요해지면 레지스트리 위에 얹는다(#211) |
| D-024 | 에이전트 구조는 에이전트 하나 + L1·L2·L3 프롬프트 오버라이딩 + 단계별 스레드다. 파이프는 `run_agent(AgentTask) -> AgentResult`(동기) 하나로 부른다 | 단계별 스레드는 "스레드마다 실행 루프"다. `run_agent`가 안에서 `Runner.run_sync`를 쓴다(#209 계획). 실행기(`soc.agent.executor`)는 단계 스레드마다 asyncio 이벤트 루프를 하나 만들어 그 스레드의 기본 루프로 등록하고, `run_sync`가 그 루프를 쓰게 한다. 루프에서 직접 비동기 코드를 돌리지는 않고, 종료할 때 진행 중인 run을 취소(`cancelled`)하는 데만 쓴다(#215) |
| D-025 | L1 판정 결과 조건. 확신도 임계값은 `[agent.l1]`의 `confidence_threshold = 0.8`이다. `pending` Alert는 `benign`이면 확신도와 관계없이 `held`(Ticket 없음), `malicious`이고 임계값 이상이면 `promoted`와 `origin=l1` Ticket 생성, 그 밖에는 `held`다. `new` Ticket은 `benign`이고 임계값 이상이면 `closed`, `malicious`이고 임계값 이상이면 `escalated`, 그 밖에는 `held`다. 실패한 작업은 최초 실행을 포함해 총 3회까지 시도하고, 마지막에도 실패하면 `held`로 둔다. `cancelled`는 실패 횟수에 넣지 않는다 | `undetermined`, 임계값 미만, 형식·근거·최종 실행 오류는 보류한다. Alert 승격과 Ticket 생성은 한 트랜잭션으로 처리하며, 현재 상태가 `pending`/`new`일 때만 결과를 적용해 재실행으로 중복 생성하지 않는다. 실패 횟수는 워커 재시작 뒤에도 유지한다. 정확한 저장 위치는 구현 이슈에서 정한다(#251) |
| D-048 | 외부 LLM으로 보내는 모델 입력(입력 데이터·도구 결과·형식 오류 재요청)은 보내기 직전에 SDK 입력 필터 한 곳에서 비밀 값을 `[REDACTED]`로 가린다. 규칙은 Agent Log 쓰기 직전 가림과 같고 같은 가림 함수를 쓴다. 가림 중 예외가 나거나 JSON 값이 아닌 타입을 만나면 원문을 보내지 않고 run을 `provider_error`로 끝낸다. 근거 ID 모양 값(접두사 + UUIDv7)은 환경변수 값 치환에서만 건너뛴다. 도구 쪽에서 비밀이 나올 자리를 미리 빼지는 않는다 | 규칙: 설정 `*_env`가 가리키는 환경변수 값(8자 이상), DB 비밀번호, `password`·`passwd`·`pwd`(값이 `/`로 시작하는 두 단계 이상 경로면 제외)·`api_key`·`token`·`secret` 계열의 `=`·`:` 값, `Bearer`, `Authorization: Basic\|ApiKey`, 비밀 키 이름의 객체 값(숫자·배열·객체 값 포함. 페이지 이동 표지 `next_token` 등은 제외). 입력 데이터와 도구 결과(`<태그>`로 감싼 JSON)는 JSON으로 풀어 객체 키 규칙을 적용하고 바뀐 것이 없으면 원문 그대로 둔다. 환경변수 값은 JSON 이스케이프 모양도 가린다. 모양을 모르는 비밀, 8자 미만 비밀, 명령줄(`--password 값`)·이름·값 쌍 헤더는 못 가린다. 한계는 `docs/security.md`. SSH `processes`의 명령줄 위험은 #213 그대로다. 필터는 같은 입력 이력이면 항상 같은 결과를 낸다(D-036 `input_from` 접두 비교). Agent Log의 model 줄 `input`과 `records` 도구 줄 `output`은 모델이 받은 입력과 같아진다(`text`·`aggregate` 도구 줄은 자르기 전 원본이다). 표시(`details.redacted`)는 만들지 않는다(#279) |
| D-051 | 위협 인텔 조회 도구 `lookup_indicator`는 VirusTotal API v3 무료 키를 httpx(D-039)로 부른다. 지표 값(IP·도메인·해시)만 보내고, 공개 주소가 아니거나 비공개 이름이거나 설정 제외 목록에 있는 값은 보내지 않는다. 캐시와 호출 한도는 프로세스 메모리에 두며 재시작하거나 프로세스가 여럿이면 따로 센다. 키는 `VT_API_KEY` 환경변수로만 읽고, 키가 없으면 도구를 등록하지 않는다 | 무료 키 약관은 상업 이용을 제한한다(PR "이유"에 적는다). 회사의 공개 도메인은 설정 제외 목록에 적지 않으면 나간다. l3는 허용하지 않는다(#309) |
| D-052 | 로컬 ATT&CK·KEV 조회 도구 `get_attack_technique`·`search_attack_techniques`·`get_cve`는 네트워크 없이 PostgreSQL의 저장본만 읽고, 허용 단계는 `l2`·`l3`다. 에이전트 읽기 역할 `soc_agent_reader`에는 `attack_techniques`·`kev_entries`·`intel_source_state`의 SELECT만 주고 `threat_news`는 주지 않는다. KEV 상세는 새 테이블 `kev_entries`에 저장하고(`threat_news`는 그대로), 응답에는 데이터 버전·수집 시각을 넣는다. KEV에 없는 CVE는 `not_in_kev`(KEV 목록에 없다는 뜻이지 악용되지 않는다는 뜻이 아님), 데이터가 없으면 `no_data`다. 도구가 읽는 ATT&CK 버전은 `[tools.local_intel] attack_version`이고 `[l3.intel.attack] version`과 함께 바꾼다 | 0300의 "에이전트 읽기 역할에 이 테이블 권한을 주지 않는다"를 이 세 테이블에 한해 바꾼 것이다. NVD 등 KEV 밖의 CVE 데이터는 적재하지 않는다. 기법·CVE 문자열은 밖에서 온 데이터로 다룬다(D-048 입력 필터를 그대로 거친다). 지난 계획·기록(221)은 고치지 않는다(#311) |
| D-053 | 유사 사례 검색 도구 `search_similar_cases`는 판정이 끝난 Ticket을 담은 Qdrant 컬렉션(용도 `ticket_verdicts`)을 임베딩 유사도로 읽고, 허용 단계는 `l1`·`l2`다. L1 판정이 적용된 직후 `verdict`가 있는 Ticket을 같은 프로세스에서 색인하며 point ID는 Ticket ID이고 payload는 비운다. 색인 텍스트는 Alert 제목·Event 요약·Hunt 문장이고 판정 이유는 넣지 않는다. 상태·판정·시각·엔티티는 PostgreSQL에서 읽으므로 `soc_agent_reader`에 `tickets`(id, status, verdict, entities, alert_ids, created_at)·`incidents`(id, ticket_ids, status)·`cases`(id, incident_id)의 열 단위 SELECT를 준다. `decided_by`는 그 Ticket의 Incident에 Case가 있으면 `human`, 그 밖에는 `agent`다. `ticket_id` 검색은 자기 자신과 같은 Incident의 Ticket을 뺀다. 실행기가 임베더를 한 번 만들어 도구 세션에 주입하며, Qdrant 환경변수나 임베더가 없으면 도구를 등록하지 않는다 | Qdrant 쓰기는 PostgreSQL 트랜잭션에 묶지 않아 누락될 수 있고 재색인 명령으로 복구한다(D-013). 판정 이유를 임베딩하지 않는 것은 질의 쪽에 이유가 없어 같은 종류의 텍스트끼리 비교하고, LLM이 쓴 문장이 검색 순위를 좌우하지 않게 하려는 것이다. `decided_by=agent` 사례 경고는 프롬프트 수준이며 D-025의 자동 종결을 구조적으로 막지 못한다. 0003의 "tickets·incidents·cases에 권한을 주지 않는다"를 이 세 표의 위 열에 한해 바꾼 것이다. `python -m soc.agent` 프로세스에 약 2.27GB 모델이 올라간다. L1 담당과 L2 담당이 확인했다(#313) |
| D-054 | 활성화 파이프 `uv run python -m soc.pipeline`은 정규화·Ticket 생성·L1·L2를 한 프로세스에서 주기 실행한다. 실행기(D-024)에 단계 이름 `normalize`·`ticketing`을 `executor.py` 안에서만 더해 같은 스레드·종료·죽음 처리(D-056)를 쓰고, 수집과 L3는 띄우지 않는다(`[executor.l3]` 값과 관계없이). 기동하면 준비 점검을 항목별 OK/FAIL로 출력하고 하나라도 FAIL이면 단계를 띄우지 않고 종료 코드 4로 끝낸다. 점검은 DB·마이그레이션(읽기만)·Qdrant·임베더 로드·LLM 실호출 1회·도구 설정을 본다. 정규화·Ticket 간격과 종료 대기 시간은 `[pipeline]`에 두고 L1·L2 간격은 `[executor.l1\|l2]`를 그대로 쓴다 | 정규화 failed 재시도는 넣지 않는다. 점검 출력에는 항목 이름과 실패 종류 코드만 낸다(주소·계정·키 값 없음). LLM은 고정 문자열만 보낸다. 키가 틀리면 L1이 첫 건부터 실패를 세어 3회째에 `held`로 두기(D-025) 때문에 기동 때 실호출로 먼저 거른다. 임베더 파일이 없으면 점검이 약 2.27GB를 내려받는다(D-044). 정규화·Ticket 배치는 종료 신호로 중단하지 못하므로 종료 대기 시간 안에 끝나지 않으면 정규화 임대(최대 10분)가 풀릴 때까지 다음 기동이 그 건을 집지 못할 수 있다. `python -m soc.agent`는 바뀌지 않고, 두 명령을 동시에 띄우는 것은 막지 않는다(#316) |
| D-055 | 도구의 동기 핸들러(DB·SIEM)는 호출마다 전용 데몬 스레드에서 돌리고 레지스트리가 `asyncio.wrap_future`로 기다린다. `async def` 핸들러(SSH)는 이벤트 루프에서 그대로 await한다. 취소하면 기다림만 끊고 진행 중인 DB 문장·HTTP 요청은 끝까지 두며 결과는 버린다. 취소로 버려진 스레드가 생기면 `soc.agent.executor` 로그에 도구 이름과 경과 시간만 WARNING으로 남긴다. `asyncio.to_thread`와 async 클라이언트(psycopg async, `httpx.AsyncClient`)는 쓰지 않는다 | `to_thread`의 기본 실행기 스레드는 프로세스 종료 때 합류돼 종료가 도구 시간만큼 붙잡히고(#278), psycopg async는 Windows 기본 이벤트 루프(`ProactorEventLoop`)에서 동작하지 않는다. 핸들러는 별도 스레드에서 돌므로 `ctx`와 자기 인자 밖의 스레드 로컬·`contextvars`에 기대지 않는다. 한계: 버려진 스레드는 DB는 접속·문장 시간 제한 안에, SIEM은 `deadline_seconds` 안에 끝나지만 DB 서버가 얼면 제한이 없다. 서버 쪽 문장 취소와 DB 정지 동작은 실제 PostgreSQL로 확인하지 못했다(#280) |
| D-056 | 실행기 단계 스레드의 예외 처리와 종료 코드. `poll`·`handle`의 `Exception`·`CancelledError`·`SystemExit`은 예외 종류만 로그에 남기고 다음 건으로 간다. 그 밖의 `BaseException`과 단계 스레드 자체의 오류는 그 단계를 죽은 것으로 표시하고, 메인 루프가 감지해 다른 단계를 정리한 뒤 종료 코드 3으로 끝난다. 죽은 스레드를 재시작하지 않는다. 종료 코드는 0 정상, 1 종료 대기 시간 초과, 2 설정 오류, 3 단계 스레드가 죽음이다 | 예외 메시지는 밖에서 온 문자열일 수 있어 남기지 않고, 스레드 밖으로 다시 올리지 않는다(`threading.excepthook`이 메시지가 든 트레이스백을 찍는다). `SystemExit`을 치명으로 두면 한 건이 프로세스를 죽이고 재시작 뒤에도 같은 건이 다시 나온다. 재시작은 `BaseException` 뒤 상태를 믿을 수 없어 하지 않고, 프로세스 재시작은 프로세스 관리자의 몫이다. 실행기는 라운드마다 워커별 받은 건수·처리 건수·처리 시간을 `soc.agent.executor`에 INFO로 남긴다. 대기 시간·DB·화면 지표는 새 이슈(#295)에서 각 담당과 정한다(#280) |
| D-058 | `query_siem` 결과는 호출의 `call_id`(`agl_`)로만 인용하고 `siem_ref`는 근거 ID로 허용하지 않는다(`evidence_id` 계약은 그대로). 히트 하나가 결과 한도의 한 몫을 넘으면 0건으로 숨기지 않고, 값 하나와 목록 길이를 모델에게 가는 직렬화 길이로 재서 줄이거나 `fields_omitted`로 바꿔 `siem_ref`는 남긴다. 원본 문서는 Agent Log tool 줄 `output.hits[].siem_ref`로 찾는다 | 뒤에서 빠진 히트의 `siem_ref`는 남지 않아 조회를 다시 해야 한다. 문서 단위 인용은 `evidence_id` 계약과 L1~L3 코드·화면을 바꾸므로 필요해지면 계약 담당과 새 이슈에서 정한다. 되짚는 법은 `docs/architecture.md`(#281) |

### L2

| ID | 결정 | 메모 |
|---|---|---|
| D-027 | Incident 분류는 Ticket·Alert·Entity 연결 그래프에서 Incident 후보 경로를 찾고, 같은 에이전트가 그래프와 경로를 보고 기존 Incident 또는 새 Incident를 선택한다(D-024). Event는 연결 경로에 쓰지 않는다. L3 Ticket은 Hunt 엔티티에서 탐색을 시작한다. 출발·상대 Alert 또는 Hunt 엔티티가 모두 `role = src`이고 타입·정규화 값이 같을 때만 후보 경로를 만든다. `src` 공개 IP도 연결 근거로 허용한다. `[l2.branch]`의 `candidate_window_ms`와 `max_candidates`로 탐색을 제한하고 `max_incident_tickets = 10`으로 Incident당 Ticket 수를 제한한다. 가득 찬 Incident는 후보 수 제한 전에 제외하고 저장 직전 잠근 뒤에도 상한을 재확인한다. 경로가 없거나 탐색 한도에 걸리거나 선택한 Incident가 가득 차면 새 Incident를 만든다. 분류는 보류하지 않는다. 그래프 경로와 탐색 상태를 Ticket의 `details.l2_branch`에 저장하고 Incident 상세 API와 L2 분석에 전달한다. L2 분류는 Qdrant `ticket_branch` 임베딩 색인을 사용하지 않는다. 저장 직전에 Ticket과 선택한 Incident를 잠그고 상태를 다시 확인한 뒤 한 트랜잭션으로 저장한다 | 수집기·목적지 엔티티를 연결 근거에서 제외하되 증거로는 보존한다. 공개 IP 단독 경로 제외와 `ipaddress` 판별은 #329에서 폐기했다. 과거 `public_ip_only` 기록의 화면 표시는 유지한다. 그래프 탐색은 설정된 시간 창·후보 수 한도 안에서만 완료를 주장하며, 한도 도달은 경로 없음과 구분해 보존한다. 새 Incident 생성은 분류의 최종 대안이며 D-028의 분석 실패 보류·재시도 정책은 바꾸지 않는다. 기존 Ticket·Incident 관계를 소급 변경하지 않는다. `ticket_branch`와 `ticket_verdicts`는 별개이며 후자는 유사 사례 검색용으로 유지한다(#319, #329) |
| D-028 | L2 재분석은 새 Ticket이 자동 분석 가능한 Incident에 붙었을 때와 사람이 반려했을 때 한다. `human_handling`에 새 Ticket이 붙어도 자동 재분석하지 않는다. L2 조사 중 찾은 근거·엔티티는 해당 라운드 판정에 쓰되 재분석 신호로 삼지 않는다. `analysis_round`는 성공·실패마다 증가하는 기록용 순번이며 상한을 두지 않는다. 연속 실패는 별도 카운터로 최초 실행 포함 3회까지만 시도하고, 소진하면 `held`로 옮긴다. `held_at`부터 설정한 쿨다운이 지나면 자동으로 `analyzing`으로 되돌려 실패 카운터를 초기화한다. `cancelled`는 어느 카운터에도 넣지 않는다. 분석 중 새 Ticket이 붙으면 현재 Artifact는 저장하되 `analyzing`을 유지해 새 Ticket을 다시 분석한다. `review_round`가 한도(기본 2)에 이르면 `human_handling`으로 넘긴다 | 조사 중 얻은 정보가 스스로 재분석을 트리거하지 않게 하면서 외부 입력으로 인한 재분석 횟수는 제한하지 않는다. 실패 한도와 쿨다운은 `[l2.analyze]` 설정 값이다. 쿨다운은 Ticket 연결 시 바뀌는 `updated_at`이 아니라 `details.l2_analyze.held_at`을 기준으로 한다. `held`에도 Ticket은 계속 붙을 수 있다 |
| D-045 | L2 분석 결과는 `incident_artifacts`에 성공한 분석 라운드마다 한 행으로 쌓고, 탐지 룰·대응 방안 제안은 `incident_proposals`에 한 건씩 나눠 둔다. `incidents`에는 `summary`·`assessed_severity`만 최신 값으로 갱신한다 | 덮어쓰지 않아 반려 뒤 재분석이 이전 라운드를 문맥으로 읽을 수 있다. 제안은 나중에 하나씩 채택·기각할 수 있게 행으로 나누지만 이번에는 채택 기능과 `status`를 만들지 않는다. 실패한 라운드는 Artifact가 없어 번호에 빈칸이 생길 수 있다. Artifact는 구조화된 행이고 화면에서는 문자열을 텍스트로만 표시한다 |
| D-072 | Incident 제목과 권고 조치 구조. L2 분석 출력에 `title`과 `recommendations`(최대 10개, 항목 `kind`=`response`\|`detection`·`priority`=`high`\|`medium`\|`low`·`title`·`detail`·`rationale`)를 두고 `detection_rules`·`response_actions`를 없앤다. 분석이 성공하면 Incident `title`을 `clean_title`(D-070)로 정리한 값으로 덮어쓰고(재분석·`not_threat` 포함), 정리 결과가 `(제목 없음)`이면 임시 제목(첫 Alert 제목)을 유지한다. 출력 계약의 `title`에는 길이·pattern을 두지 않는다. 권고 조치는 `incident_proposals` 행으로 저장하며(`body`→`detail`, `title` 필수, `priority`·`rationale`은 옛 행만 `null`, `seq`는 목록 전체 순서) 옛 행은 마이그레이션 0202가 변환한다. Incident 계약은 바꾸지 않는다 | 계약 검증이 빈 제목·긴 제목에서 실패하면 분석 전체가 `save_failure`로 가서 같은 Incident를 다시 분석하다 `held`가 된다(D-059 유형). 제목은 부수 값이라 저장 시점에 정리한다. 목록 항목은 본문이라 한도를 넘으면 자르지 않고 거부한다(개수 ≤10, `title` ≤200자, `detail` ≤2000자, `rationale` ≤1000자). 제안을 행으로 두는 설계(D-045)는 그대로다. 옛 행의 `priority`·`rationale`은 지어 채우지 않고 `null`로 둔다. AI 제목이 후보 Incident의 `title`로 브랜치 판단 입력(`l2/branch/decide.py`)에 들어가는 변화를 받아들였다(#344) |

### L3

| ID | 결정 | 메모 |
|---|---|---|
| D-029 | L3 위협 시나리오 입력은 보안 뉴스(보안뉴스·The Hacker News RSS, CISA KEV)와 MITRE ATT&CK을 코드(`soc.l3.intel`)로 수집한다. 에이전트에는 웹 접근을 주지 않는다 | 수집한 제목·요약은 밖에서 온 문자열이다(`docs/security.md`). 에이전트에는 L3 헌팅 코드가 `AgentTask.data`로만 넘긴다(#221) |
| D-030 | L3 실행 방식. 실행기(`uv run python -m soc.agent`)의 L3 단계에서 생성 워커(수집 → 가설 생성, `soc.l3.hunt.generate`)와 검증 워커(`soc.l3.hunt.verify`)로 주기 실행한다. 수동 명령(`uv run python -m soc.l3 hunt`)은 그대로 둔다. 기본은 꺼짐(`[executor.l3] interval_seconds = 0`)이고 `config/local.toml`에서 켠다 | 가설 생성은 마지막 시도부터 `[l3.hunt] generate_interval_seconds`(기본 하루)마다 한다. 마지막 시도는 `cancelled`가 아닌 `l3_hypothesize` Agent Log와 프로세스 안 기록 중 늦은 것이다. 종료로 `cancelled`가 된 검증 run은 시도 횟수에 넣지 않는다(#245) |
| D-040 | 데이터셋 MITRE ATT&CK Enterprise(공식 STIX JSON, `mitre-attack/attack-stix-data`). 원본은 커밋하지 않고 실행할 때 받아, 폐기·대체되지 않은 기법의 ID·이름·전술·버전과 설명(길이를 자른 평문)·탐지 데이터 소스·수집 시각만 저장한다 | 버전마다 쌓고 쓰는 쪽이 설정 버전으로 고른다. 이용 약관에 따라 README "제3자 데이터" 절에 MITRE 고지문을 싣는다(#221). 설명·탐지 데이터 소스·수집 시각은 로컬 조회 도구를 위해 더했다(#311). 탐지 데이터 소스는 20.0 번들의 detects 관계로 이어진 탐지 전략·analytic의 data component 이름이다 |

### 저장

| ID | 결정 | 메모 |
|---|---|---|
| D-012 | RDB는 PostgreSQL | |
| D-013 | 벡터 DB는 Qdrant. 판정이 끝난 Ticket·Case를 넣고 용도마다 컬렉션을 따로 둔다. L2 분류 후보용 컬렉션에는 Incident에 붙은 `linked` Ticket을 넣고 payload에 소속 Incident를 달아, 새 Ticket과 비슷한 Ticket이 속한 Incident를 후보로 삼는다 | Incident는 Ticket이 붙을수록 텍스트가 길어져 닮은 부분이 묻히거나 입력 길이에서 잘릴 수 있으므로 통째로 임베딩하지 않는다. 분류 후보용 컬렉션은 PostgreSQL을 베낀 파생 색인이고 payload의 관계는 복사본이며 권위 원본은 PostgreSQL이다. 일부 point 누락은 자동으로 감지하지 않고 PostgreSQL에서 컬렉션을 다시 만드는 명령으로 복구한다. Qdrant 쓰기는 PostgreSQL 트랜잭션이나 outbox에 묶지 않는다. 유사 사례 검색용 컬렉션(`ticket_verdicts`, D-053)에는 판정이 있는 Ticket을 넣고, Case는 별도 point로 넣지 않고 Ticket의 Incident에 Case가 있다는 사실로 읽는다(#313) |
| D-014 | Ticket·Case는 외부 도구 없이 자체 테이블과 내부 화면으로 관리한다 | |
| D-031 | 기본 임베딩 모델은 BAAI bge-m3의 dense 표현이며 로컬 ONNX로 실행한다. 기본 벡터는 1024차원이고 거리 방식은 Cosine이다. 모델 ID와 revision은 설정 값이며 컬렉션 이름은 용도·모델 ID·revision에서 파생한다 | sparse·multi-vector는 쓰지 않고 torch를 설치하지 않는다. 실행 라이브러리는 D-044를 따른다. revision은 설정 값이지만 고정한다. 임베더가 출력 차원을 알려 주고 컬렉션은 그 값을 사용해 작은 차원의 가짜 임베더로도 테스트할 수 있게 한다 |
| D-044 | 벡터 DB 클라이언트와 임베딩 실행은 `qdrant-client==1.20.0`, `onnxruntime==1.31.1`, `huggingface-hub==2.4.0`, `tokenizers==0.23.3`, `numpy==2.5.4`. FastEmbed는 bge-m3를 공식 지원하지 않아 쓰지 않고, torch를 끌어오는 경로도 쓰지 않는다 | 2GB가 넘는 torch를 `uv sync`와 CI에 올리지 않기 위해서다. bge-m3 ONNX는 외부 데이터 방식이라 `model.onnx`와 함께 약 2.27GB의 `model.onnx_data`를 요구하고, tokenizer 파일도 같은 revision에서 받는다. 모델 ID와 revision은 설정 값이다(D-031). 파일은 Hugging Face 기본 캐시(심링크)가 아니라 `<HF_HOME>/soc-onnx/<모델 ID>/<revision>`에 실제 파일로 받는다. onnxruntime이 심링크 캐시의 외부 데이터 경로를 거부해 macOS·Linux에서 모델이 열리지 않았기 때문이다(#313) |

### 데이터 계약 · DB

| ID | 결정 | 메모 |
|---|---|---|
| D-026 | Ticket 출처(`origin`)는 `auto`(기본 모드), `scenario`(시나리오 일치), `l1`(L1 1차 판정으로 승격), `l3`(L3 헌팅 발견) 네 가지다 | 값을 더하는 것은 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다 |
| D-033 | Ticket 생성 모드. 기본 `auto`는 모든 알럿을 Ticket으로 만든다. 설정으로 `scenario`를 켜면 룰 ID 목록과 일치하는 알럿은 바로 Ticket으로 만들고, 나머지는 L1 1차 판정 후 승격하거나 보류한다. 시나리오 일치 Ticket도 L1 Ticket 판정을 거친다 | 2026-11-03 교수님 답변: 금융당국이 요구하는 감사·증적용 알럿은 강제로 Ticket을 만들고, 룰 ID 기반으로 정적 설정한다. 그런 구조가 없는 기업도 쓸 수 있게 시나리오 모드는 선택이다. 설정 키는 `[ticketing] mode`(`auto` \| `scenario`), `[ticketing] scenario_rule_ids`(룰 ID 목록). 정규화는 W02(#234), 정책 분기와 직접 Ticket 생성은 W04(#246)에서 한다 |
| D-034 | ID는 접두사 + UUIDv7 문자열이다. UUIDv7은 라이브러리 없이 직접 구현하고, 같은 밀리초 안에서도 만든 순서가 지켜지게 카운터를 둔다 | Python 3.13 표준 라이브러리에 UUIDv7이 없다. 순서 보장은 한 프로세스 안에서만이고, 프로세스끼리는 밀리초 단위까지 맞는다. 접두사 목록은 `soc.ids`가 기준 |
| D-035 | DB 마이그레이션은 `src/soc/db/migrations/`의 순번 SQL 파일과 실행기(`uv run python -m soc.db.migrate`)로 한다. 번호 대역: 0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3 | 적용한 파일은 고치지 않고 새 번호를 만든다. 파일은 자기보다 작은 번호의 파일이 만든 테이블만 참조한다(빈 DB에서는 번호 순서로 실행되므로) |
| D-036 | Agent Log는 모델·도구 호출의 입출력을 PostgreSQL에 저장한다. 호출이 끝날 때마다 그 줄을 바로 쓴다. model 줄의 입력은 줄마다 새로 더해진 항목만 저장하고, `records` 도구 줄의 출력은 모델에게 보인 결과만 저장한다 | 성능 문제가 생기면 NoSQL을 다시 논의한다. 입출력에는 공격자가 쓴 문자열이 들어가므로 화면에서는 텍스트로만 표시한다(로그 원문·LLM 출력 텍스트 표시, D-019). 복원: 같은 `run_id`의 model 줄을 `seq` 순으로 이어 붙이면(system 지시는 첫 줄, 이후 줄은 `input_from`) 그 호출의 전체 입력이 된다. 그 입력은 모델에게 보낸 값이라 비밀 가림이 적용된 뒤의 값이다(D-048). model 출력 줄·`details`·도구 인자 줄은 쓰기 직전에만 가려, 모델이 낸 원문과 다를 수 있다(#279). 앞 입력의 접두가 아니면 전체를 저장하고 `details.input_reset`을 단다. `records` 도구 줄은 모델에게 보인 결과와 뺀 건수(`omitted`)를 담는다. 도구 결과를 자르기 전 전체로 저장하던 방식(#211)을 바꾼 것이다. 읽는 규칙: 끝난 run에는 `details.validation` 또는 `details.failure`가 있는 model 줄이 있고, `details.sent=false` 줄은 모델에 보내지 않은 호출이다. 줄을 호출마다 쓰므로 강제 종료된 run은 끝난 호출까지만 남고 그 줄이 없다(#278) |
| D-037 | 계약 검증·DB 라이브러리: psycopg 3(`psycopg[binary]`), jsonschema, pydantic v2. 개발용: datamodel-code-generator | psycopg는 LGPL-3.0이고 수정 없이 import해서 쓴다. 생성 도구 버전은 `uv.lock`으로 고정한다 |
| D-038 | 생성 코드 폴더(`src/soc/contracts/generated/`)에서만 ruff E501(줄 길이)을 끈다. 포맷 검사와 나머지 린트 규칙은 그대로 적용한다 | 생성 코드는 손으로 고칠 수 없고, schema의 설명 문장이 한 줄로 생성돼 100자를 넘는다. 2026-11-03 #192 계획에서 사람이 승인한 예외 |
| D-070 | Ticket 제목. Ticket 계약에 필수 `title`(1~200자)을 두고 `tickets.title`(NOT NULL)을 더한다. 제목 규칙은 `soc.ticketing`의 `clean_title`·`ticket_title` 한 곳이다. 공백 목록(탭·LF·VT·FF·CR·공백·U+00A0·U+3000)의 연속을 한 칸으로 줄이고 앞뒤를 떼며, 200자(코드포인트)를 넘으면 앞 199자 + `…`이고, 목록 밖 글자가 하나도 없으면 `(제목 없음)`이다. 계약 `pattern`(`^[\t\n\u000b\f\r \u00a0\u3000]*[^\t\n\u000b\f\r \u00a0\u3000][\s\S]*$`)·DB CHECK(`title ~ E'[^\t\n\u000b\f\r \u00a0\u3000]'`)·`clean_title`이 같은 공백 목록을 쓴다. 계약 pattern은 앞뒤를 고정해야 해서 "목록 밖 글자가 하나 이상"을 이렇게 쓴다. 값은 auto·scenario·l1이 소속 alert의 제목(시나리오는 alert 하나당 Ticket 하나이므로 그 alert의 제목), l3가 Hunt `hypothesis`다. alert가 여럿이면 심각도 내림차순 → time 오름차순 → id 오름차순으로 첫 alert의 제목을 쓰는 순수 함수를 두되, auto·scenario·l1은 alert가 정확히 1개라(0104) 생성 경로는 하나만 넘긴다. 기존 행은 마이그레이션 0109가 같은 규칙으로 채운다. 목록 API `TicketItem`에 `title`을 더하고 L2 모델 입력에 `title`이 포함된다 | 공백뿐인 값의 기준을 `\S`로 하지 않은 것은 `\S`가 유니코드 공백 전체를 공백으로 봐서, `clean_title`을 통과한 U+2003만 있는 제목을 계약이 거부하고 `run()`이 같은 alert를 매번 다시 시도해 D-059 문제가 다시 생기기 때문이다. 폴백 문구는 생성 코드와 백필이 같다. 제목은 생성 시점 값이라 alert 제목이 재처리(D-063)로 바뀌어도 따라가지 않는다. L3 제목은 LLM 출력(`hypothesis`)이라 데이터·텍스트로만 다룬다. 공통 계약 변경이라 L1·L2·L3·UI 담당이 계획 확정 전에 승인했다. 계획은 `docs/plans/343-ticket-title.md`(#343) |

### 화면

| ID | 결정 | 메모 |
|---|---|---|
| D-015 | 화면은 React + Vite + TypeScript | |
| D-016 | 화면용 API는 FastAPI | |
| D-042 | 화면용 API 실행·의존성: `fastapi==0.162.0`, `uvicorn==0.54.0`. 테스트는 Starlette TestClient(`httpx2`)로 한다 | 기본 바인딩은 127.0.0.1이다. 인증(D-020)이 생겼어도 기본값은 그대로 두고 설정(`[api] host`)으로 바꾼다(#284). TestClient는 HTTP 클라이언트(httpx, D-039)가 아니라 openai가 끌어오는 `httpx2`를 쓴다(#239) |
| D-017 | 화면 세부 도구: Tailwind CSS + shadcn/ui, TanStack Query, React Router, MSW(mock API), Vitest + Testing Library, Node LTS + pnpm, ESLint + Prettier | frontend/에서 pnpm lint(ESLint + Prettier 검사), pnpm test(Vitest run), pnpm build(TypeScript 검사 + Vite 빌드). CI도 같은 명령(#266) |
| D-018 | 차트는 Recharts | |
| D-019 | 로그 원문과 LLM 출력은 화면과 알림에서 텍스트로만 표시한다 | `docs/security.md` "화면" |
| D-046 | 화면 폰트는 @fontsource 패키지(`@fontsource/inter`·`roboto-mono`·`michroma`·`jura` 5.3.0, OFL-1.1)로 번들하고 외부 폰트 CDN을 부르지 않는다 | 한글은 시스템 폰트로 대체한다(#274) |

### 계정

| ID | 결정 | 메모 |
|---|---|---|
| D-020 | 사용자 계정을 만든다. 처음 실행할 때 랜덤 문자열로 최초 관리자를 만들고, 비밀번호를 바꾼 뒤 쓴다. 그 밖의 사용자는 회원가입 후 관리자 승인으로 쓴다 | 서버 세션 + HttpOnly 쿠키이고 DB에는 토큰 해시만 둔다. 역할은 admin·analyst다. 최초 관리자의 임시 비밀번호는 서버 시작 때 표준 출력에 1회만 내고 `logging`·DB·파일에 평문으로 두지 않는다. `/api`는 기본 거부이고 공개 라우트만 명시한다. 권한은 `<자원>.<동작>` 이름으로 admin이 사용자별로 부여·회수하고 admin은 항상 전체 권한이다. analyst는 가입 승인 때 조회 권한을 기본으로 받는다(#284) |
| D-047 | 비밀번호 해시는 argon2-cffi(`argon2-cffi==25.1.0`, Argon2id) | 라이브러리 기본 파라미터를 쓴다. 함께 들어오는 `argon2-cffi-bindings`는 `uv.lock`으로 고정한다. PyPI 메타데이터에 라이선스가 비어 있어, 개발 때 설치한 패키지의 LICENSE 파일로 Apache-2.0 호환 여부를 확인하고 notes에 적는다(#284) |

### 설정 (개발 필요)

| ID | 결정 | 메모 |
|---|---|---|
| D-021 | SIEM 연결 설정 화면을 만든다. 화면에서 저장한 설정(프로필)은 PostgreSQL에 두고 설정 파일과 환경변수보다 우선하며, 바꾸면 바로 반영한다. 조회를 포함해 관리자만 접근한다 | 아직 개발되지 않았다. 비밀 값 저장 방식은 이 이슈에서 정하고, 그전까지는 환경변수 이름만 저장한다(`docs/security.md`). 고를 수 있는 환경변수는 `SIEM_` 접두사로 제한한다(`docs/security.md`) |
| D-043 | 런타임 Ticket 정책은 TOML 기본값 위에 PostgreSQL의 단일 활성 정책 행을 적용하고, 관리자 인증 API로 전체 값을 바꾼다. Alert마다 분기 직전에 정책을 읽으며 이미 저장한 분기 결과는 바꾸지 않는다 | 활성 행이 없으면 TOML을 쓴다. 정책 이력은 저장하지 않는다. 조회는 `policy.read`, 변경은 `policy.update` 권한이다(#246, #284) |

## 후보 (의논 필요)

| ID | 안건 | 후보 | 메모 |
|---|---|---|---|

## 담당자가 정함

그 단계를 구현하는 담당자가 계획 이슈에서 정한다. 예시는 이전 논의에서 나온 안이며 그대로 따를 필요는 없다.

| ID | 정할 것 | 예시 | 담당 단계 |
|---|---|---|---|

## 추후

| ID | 항목 | 메모 |
|---|---|---|
| D-032 | 알림 | 추후 개발 예정. 이전 안: Slack, L2 분석이 끝나 사람 승인이 필요할 때만 |
| D-071 | 시나리오 모드 묶음 Ticket의 요약 제목 | 여러 alert를 묶은 Ticket이면 AI가 분석한 뒤 요약한 제목을 쓴다. 지금은 계약과 DB가 auto·scenario·l1 Ticket의 alert를 1개로 제한해(`ticket.schema.json`, 0104) 묶음 Ticket을 만들 수 없다. 계약이 묶음을 먼저 허용해야 하고, 요약 생성은 시나리오 로직 이슈에서 만든다. 원본 alert 하나당 Ticket 하나이면 alert 제목을 쓴다(D-070). 코드 주석은 `_make_ticket` 근처에 있다(#343) |

## 폐기

| ID | 항목 | 이유 |
|---|---|---|

## 기록

새 기록을 맨 위에 쓴다.

- #344 · Incident 제목과 권고 조치 구조(D-072)를 확정으로 추가했다. L2 분석 출력에 `title`·`recommendations`를 더하고 `detection_rules`·`response_actions`를 없앤다. Incident 제목은 분석 성공 시 `clean_title`로 정리해 덮어쓰고 폴백이면 임시 제목을 유지한다. 권고 조치는 `incident_proposals` 행으로 저장하고 옛 행은 마이그레이션 0202로 변환한다(`priority`·`rationale`은 `null`). D-045의 행 단위 저장은 그대로 두고 이 결정이 항목 모양을 바꾼다. 사용자가 정함.
- #343 후속 · D-070의 계약 pattern 표기를 `^…$`로 고정한 형태로 고쳤다. 기존 테스트(`test_schema_patterns_are_anchored_at_both_ends`)가 모든 계약 pattern의 앞뒤 고정을 요구해서, 뜻(공백 목록 밖 글자가 하나 이상)은 그대로 두고 표기만 바꿨다. DB CHECK는 `~`가 검색이라 고정하지 않은 형태 그대로다. 사용자가 정함.
- #343 · Ticket 제목(D-070)을 확정으로, 시나리오 묶음 Ticket의 요약 제목(D-071)을 추후로 추가했다. Ticket 계약에 필수 `title`(1~200자)을 두고 `tickets.title`을 마이그레이션 0109로 채운다. 제목 규칙(공백 정리·199자 + `…`·폴백 `(제목 없음)`)과 공백 기준(명시한 8종, `\S`를 쓰지 않음)을 정했다. L3 Ticket 제목은 `hypothesis`이고, 다중 alert 규칙은 함수로만 두며 생성 경로는 alert 하나다(auto·scenario·l1은 alert 1개). 목록 API에 `title`을 더하고 L2 모델 입력에 `title`이 포함된다. 공통 계약 변경이라 L1·L2·L3·UI 담당이 계획 확정 전에 승인했다. 사용자가 계획을 확정함.
- #349 · 이벤트 매핑표의 구성과 클래스 결정(D-069)을 확정으로 추가했다. 4002는 클래스 공통 ECS 층과 소스별 층(nginx, ModSecurity)으로 나누고, 클래스는 소스 표의 `detect`로 정한다(D-067 보완, D-068의 표 위치 서술 보완). ECS 허용 목록, 시간대 없는 시각의 UTC 간주와 읽을 수 없을 때 실패, 이벤트 `outcome`은 후속으로 정했다. 엔티티 출력과 `ocsf` 모양, 기존 이벤트 클래스 변경은 L2·L3·UI·알럿 담당 확인이 필요하다.
- #347 · Event 저장·계약 구조(D-068)를 확정으로 추가했다. `events.ocsf`가 원본이고 파생 컬럼은 단일 함수가 만들며, Event JSON 최상위를 OCSF 문서로 두고 우리 쪽 값 4개를 `details`에 모은다. 클래스별 요약 정의(`mapping_tables/events/`), `activity_id = 99`의 `activity_name`, `reprocess --kind event`를 정했다. D-066의 `get_event` 서술을 대체한다. 공통 계약 변경이라 L1·L2·L3·UI 담당 확인이 필요하다.
- #340 · 이벤트 수집 대상의 OCSF 클래스를 설정 `class`로 선언하는 규칙(D-067)을 확정으로 추가했다. 틀린 `class`와 알 수 없는 키는 수집을 멈추지 않고 Base Event(0)·무시로 두며 stderr에 경고한다(QA에서 `calss` 오타가 조용히 무시되는 것을 관찰했고, 사람이 멈추지 않기로 정함). 허용 번호는 `ocsf/classes/`의 공식 정의 기준이고 2003·3002·4001·4002·4003·6003 정의를 받아 둔다(D-061의 고정 범위 확대). 2004·알럿 대상 사용 금지, 생략 시 기존 동작 유지. 이벤트 매핑표 위치는 `mapping_tables/events/`. 정규화 연결은 DB 스키마 개편 결정 뒤 후속 이슈로 둔다. 사용자가 계획을 확정함.
- #339 · Alert 계약 구조(D-066)를 확정으로 추가했다. Alert JSON 최상위를 OCSF 문서로 두고 우리 쪽 값 6개를 `details`에 모으며, 조립 함수 한 곳·`details`를 뺀 OCSF 검증·`id_fields` 점 경로 확장을 정했다. D-059의 계약 서술과 D-065의 "계약·읽는 쪽 코드는 바꾸지 않는다"를 대체한다. `rule_id`는 `details`에서 필수이되 null을 허용한다. 공통 계약 변경은 L1·L2·L3·UI 담당이 계획 확정 전에 승인했다. 사용자가 계획을 확정함.
- #338 · Alert 저장 구조(D-065)를 확정으로 추가했다. `ocsf`가 원본이고 파생 컬럼은 단일 함수가 만들며 `observables`·`evidences`는 entities에서 만든다. D-062의 `evidences` 서술을 대체한다. 시드 픽스처·코드·`ocsf` 내용 변화는 L1·L2·L3 담당자 확인을 사용자가 받아 알린다. 사용자가 계획을 확정함.
- #336 · 매핑표 엔티티 항목의 `when`과 소스 표 `entries`의 `common` 덮어쓰기, GuardDuty 판별의 표 이동(D-064, D-060 예외·D-062의 해당 부분 대체)을 확정으로 추가했다. OUTBOUND 로컬 IP가 `src`가 되어 L2 그래프 연결에 주는 영향은 담당자 확인을 사용자가 받아 알린다. 사용자가 계획을 확정함.
- #334 · 기존 알럿을 id를 유지한 채 다시 정규화하는 재처리 명령(D-063)을 확정으로 추가했다. 갱신 컬럼, 대상 한 건(`result_id`), 건너뛰는 조건(폴백·오류·`outcome` 하락), 임베딩·묶음 미재생성을 정했다. 사용자가 계획을 확정함.
- #332 · 매핑표에 엔티티 선언과 목록 `field` `detect`를 추가하고 ModSecurity·Suricata 판별을 표로 옮긴다(D-062, D-061의 해당 부분 대체). ModSecurity 알럿에 dst 엔티티가 생겨 L1·L2·L3가 읽는 데이터가 바뀐다(담당자 확인은 사용자가 받아 알린다). 사용자가 계획을 확정함.
- #328 · 소스별 매핑표 형식(YAML, PyYAML `safe_load`)과 선언형 매핑표 규칙을 확정으로 추가(D-060, D-061). OCSF 정의는 공식 API 순회로 고정하고 런타임 검증이 느슨해지는 것을 받아들였다. 사용자가 계획을 확정함.
- #329 · Incident 그래프의 연결 근거를 양쪽 `src` 엔티티로 제한하고 `src` 공개 IP를 허용한다. Incident당 Ticket 10개 상한을 후보 조회와 저장 직전에 적용한다. 기존 관계는 소급 변경하지 않고 과거 `public_ip_only` 화면 표시는 유지한다(D-027). 사용자가 계획을 확정함.

- #326 · Alert 정규화 뼈대 규칙(D-059)을 정했다. 시각·`rule_id`·엔티티 role 규칙, class 0 폴백 Alert, `normalize_status`의 `outcome`·`missing_fields`·`source`, 정규화 결과의 민감 헤더 마스킹, Alert 계약 `class_uid`를 2004 또는 0으로 넓히는 것. 공통 계약 변경이라 PR에서 L1·L2·L3 담당자 승인이 필요하다. domain 값이 IP 형식이면 `ip`/`dst`로 분류한다. 사용자가 계획을 확정함.
- #281 · SIEM 조회 결과의 인용 방식(`call_id`만 인용, `siem_ref`는 근거 ID가 아님)과 한도를 넘는 히트를 0건으로 숨기지 않는 처리(D-058)를 정했다. `evidence_id` 계약은 바꾸지 않는다. 사용자가 계획을 확정함.
- #317 · 수동 수집 명령의 첫 실행 범위·겹침 구간·체크포인트 후퇴 방지·동시 실행 방지·`tls` 실패 종류(D-057)를 정했다. 공유 함수 `store.save_page`의 체크포인트 갱신 조건을 바꾼다. 사용자가 계획을 확정함.
- #280 후속 · 결정 번호 중복을 정리했다. 수집 쪽 D-049(원본 text 보관, #277)와 D-050(격리 정책, #294)은 그대로 두고, #280의 동기 도구 핸들러 스레드는 D-055, 실행기 단계 스레드의 예외 처리·종료 코드 3은 D-056으로 다시 매겼다. 코드·설정 주석, 테스트, #280 계획·기록, D-054 행에서 #280 결정을 가리키던 D-049·D-050을 고쳤다. 지난 계획·기록(`docs/plans/309·313·316`)에 남은 '도구 핸들러 스레드(D-049)'와 '실행기 종료 처리(D-050)'는 D-055·D-056으로 읽는다. 팀 합의(#280).

- #319 · Incident 분류와 L2 분석 입력을 Ticket·Alert·Entity 그래프 경로 기반으로 바꾸고 D-027을 대체했다. Event 연결 제외, L3 Hunt 출발점, 공개 IP 단독 연결 제외, 탐색 한도 미완료 시 새 Incident, Ticket 상세 저장 및 API·화면 전달을 확정했다. `ticket_branch`는 제거하고 `ticket_verdicts`와 D-028 분석 실패 처리는 유지한다.

- #316 · 활성화 파이프(D-054)를 추가했다. 정규화·Ticket 생성을 실행기 단계로 더해 L1·L2와 한 프로세스에서 돌리고, 기동 때 준비 점검(LLM 실호출 1회 포함)을 한다. 이 이슈에서 `docs/decisions.md`의 머지 충돌 표식 3줄을 지웠고, 중복된 D-049·D-050 ID는 고치지 않았다. 사용자가 계획을 확정함.
- #313 · 임베더가 모델 파일을 Hugging Face 캐시 대신 `<HF_HOME>/soc-onnx/…`에 받도록 고쳤다(D-044 메모). 사용자가 이 이슈에서 고치기로 정함.
- #313 · 유사 사례 검색 도구(D-053)를 추가했다. 판정이 끝난 Ticket 전용 컬렉션과 색인 코드를 이 이슈에 포함하고, 에이전트 읽기 역할에 `tickets`·`incidents`·`cases`의 지정 열 SELECT를 준다. 이슈의 `kind` 인자는 두지 않고 결과에 `case_id`·`decided_by`를 넣는다. 사용자가 계획을 확정함.
- #311 · 로컬 ATT&CK·KEV 조회 도구(D-052)를 추가했다. 요청 필드가 저장되어 있지 않아 수집을 확장하고 ATT&CK 데이터셋 저장 필드(D-040)에 설명·탐지 데이터 소스·수집 시각을 더했다. 에이전트 읽기 역할에 새 테이블 세 개의 SELECT를 준다(`threat_news` 제외). L3 담당(이슈 담당)이 확인했고 사용자가 계획을 확정함.
- #309 · 위협 인텔 조회 도구(D-051)를 추가했다. VirusTotal 무료 키, 지표 값만 전송, 캐시·한도는 프로세스 메모리, 키가 없으면 도구 미등록. 사용자가 계획을 확정함.
- #280 · 동기 도구 핸들러를 호출마다 전용 데몬 스레드에서 돌리는 방식(D-055)과 실행기 단계 스레드의 예외 처리·종료 코드 3(D-056)을 추가했다. 팀 합의(#280). 사용자가 계획을 확정함.
- #294 · PostgreSQL 유일 인덱스의 키 길이 한계를 막도록 Base64url 페이로드가 128자를 넘으면 `h` + JSON 바이트 SHA-256 hex로 축약하기로 정했다. 원문은 계속 `original_text`에 보존한다.
- #294 · 수집 불가 hit 격리·재시도 정책(D-050)을 확정했다. 격리 전용 키·페이지 원자 저장·별도 재시도 예산·실행별 격리 건수를 정했다. 계획 218의 문서 단위 정지 원칙을 대체하며 기존 계획 파일은 수정하지 않는다.
- #277 · D-049 결정 반영(사람이 정함). 에이전트에게 보이는 `siem_ref`는 저장 키(`siem_ref_key`, 이스케이프된 값)다. `link_by_refs`는 저장 키 쌍(`SiemRefKey`)을 받고 안에서 이스케이프하지 않는다. 한 dict 안에서 키가 이스케이프 뒤 겹치면 값을 덮어쓰지 않고 `escape_collision` 실패로 기록한다(마이그레이션 없음, `error_code`에 CHECK가 없다).
- #277 · 원본 보관 형식(D-049)을 추가했다. `raw_records` 원본을 jsonb 대신 JSON 글자(`original_text`, `ensure_ascii=True`)로 보관하고, 정규화 결과의 NUL·짝 없는 서로게이트를 값과 키 모두 6글자 이스케이프로 치환한다. 계약 필드 `original` → `original_text`. 사용자가 계획을 확정함.
- #277 · 알려진 한계 두 가지(깨진 원본이 claim에서 배치를 멈춤, 치환 결과의 구별 불가와 키 충돌)는 `docs/notes/277-raw-original-text.md`에 문서화했다. 코드는 바꾸지 않았다.

- #279 · 모델 입력 비밀 값 가림(D-048)을 추가했다. 외부 LLM으로 보내는 입력을 SDK 입력 필터 한 곳에서 가리고, 가림 실패는 `provider_error`로 끝낸다. 환경변수 값 가림 최소 길이를 4에서 8로 올리고 `token`·`secret`·`Authorization: Basic|ApiKey` 모양을 더했다. D-036 메모의 복원 설명을 "모델에게 보낸 가림 적용 후 입력"으로 맞췄다. 팀 공유가 필요하다. 사용자가 계획을 확정함.

- #278 · Agent Log 저장 방식(D-036)을 고쳤다. 호출이 끝날 때마다 줄을 바로 쓰고, model 줄 입력은 새로 더해진 항목만, `records` 도구 줄 출력은 모델에게 보인 결과만 저장한다. 복원 방법과 "끝난 run" 읽는 규칙을 메모에 적었다. #211 기록의 "자르기 전 전체 결과 저장"을 바꾼다. 팀 공유가 필요하다. 사용자가 계획을 확정함.
- #270 · L2 재분석 횟수 한도(D-028)를 없애고 실패 재시도 3회·`held`·1시간 쿨다운 복귀를 확정했다. 분석 중 Ticket이 붙으면 현재 Artifact를 저장하고 새 Ticket을 재분석한다.

- #284 · 사용자 계정(D-020)을 개발 필요에서 확정으로 옮기고 세션·최초 관리자·기본 거부 방식을 메모에 적었다. 비밀번호 해시 argon2-cffi(D-047)를 추가했다. D-042의 "인증이 생기면 다시 정한다"는 기본 바인딩 127.0.0.1 유지로 닫았다. #246 기록의 "접근 제어 없이 노출"은 정책 조회·변경 권한 적용으로 닫았고 D-043 메모를 맞췄다. admin이 사용자별로 권한을 부여·회수하는 권한 층을 D-020에 더했고, 위임 범위는 구현된 API 전부다. 사용자가 계획을 확정함.
- #274 · 화면 폰트 번들 방식(D-046)을 확정했다. 사용자가 UI 개선 계획을 확정함.

- #266 · 화면 검사 명령(D-017)과 API 응답 TypeScript 생성 방식(D-003)을 확정했다. 사용자가 UI 연결 계획과 추가 시드 안전 조건을 확정함.

- #245 · L3 실행 방식(D-030)을 담당자가 정함에서 확정으로 옮김. 실행기 L3 단계에서 생성·검증 워커로 주기 실행, 수동 명령 유지, 기본 꺼짐. L3 담당이 정함(#245)
- #261 · L2 분석 결과 저장(D-045)을 Artifact·제안 테이블로 확정하고, D-028의 새 Ticket 재분석은 자동 분석 가능한 Incident에만 적용한다고 명확히 함. L2 담당이 정함
- #250 · Incident 분류 방법(D-027)에서 엔티티 등급·겹침을 제거하고 후보 경로를 최고 유사도 순 vector와 최근 활동순 recent로 확정했다. 에이전트나 코드 검사가 실패하면 기존 후보에 붙이지 않고 새 Incident를 만들며, 저장 직전 Ticket과 Incident 상태를 다시 확인한다. L2 담당이 정함(#250)
- #257 · 벡터 DB 클라이언트와 임베딩 실행 라이브러리(D-044)를 버전과 함께 확정하고, 임베딩 모델(D-031)이 D-044를 가리키게 함. L2 담당이 정함(#257)
- #248 · Incident 분류 방법(D-027)의 후보 경로를 벡터 검색 우선·직접 조회 선택과 fallback으로 바꾸고, Qdrant(D-013)에 용도별 컬렉션과 분류 후보용 `linked` Ticket 적재를 명시함. 팀 합의(#248). 기본 임베딩 모델(D-031)을 bge-m3 dense·로컬 ONNX·1024차원·Cosine으로 확정하고 모델 ID·revision별로 컬렉션을 가름. L2 담당이 정함
- #251 · L1 판정 결과 조건(D-025)을 확정했다. `[agent.l1].confidence_threshold`는 0.8이고, 확정 판정만 상태에 적용한다. Alert 1차 판정의 benign은 `held`, 임계값 이상 malicious는 Ticket으로 승격한다. Ticket은 임계값 이상 benign이면 `closed`, malicious이면 `escalated`; `undetermined`·낮은 확신도·최종 실패는 `held`다. 실패는 최초 실행 포함 3회까지 시도하고 `cancelled`는 세지 않는다. 상태를 다시 확인한 뒤 Alert 갱신과 Ticket 생성을 한 트랜잭션으로 한다. 실패 횟수의 저장 위치는 구현 이슈에서 정한다.
- #234 · D-007 검증 방식을 클래스별 공식 JSON Schema 파일에서 OCSF 서버의 1.9.0 클래스·객체 정의로 바꾼다. OCSF가 클래스별 JSON Schema를 배포하지 않는다는 근거로 사람이 B안을 승인했다. 계획과 구현 위치는 `docs/plans/234-ocsf-alert-event.md`의 "바뀐 점"과 `src/soc/normalize/ocsf/SOURCE.md`에 기록했다.
- #246 · D-033 구현 메모를 갱신해 정규화(W02)와 정책 분기·직접 Ticket 생성(W04)의 경계를 나눈다. D-043 추가: 관리자 API가 갱신한 단일 PostgreSQL 정책 행은 TOML보다 우선하고, Alert별 스냅샷을 적용한다. 기존 분기 결과는 유지하며 이력은 저장하지 않는다.
- #246 · 사용자가 W04 정책 API를 앱에 연결하되 인증·인가는 후속 작업으로 미루도록 정했다. W04 API는 인증 연결 전까지 접근 제어 없이 노출된다.
- #215 · 기본 LLM(D-009) 메모: Foundry는 strict를 켜면 빈 응답이라 `strict_mode` 기본값을 `false`로 함. 에이전트 구조(D-024) 메모: 실행기가 단계 스레드마다 이벤트 루프를 만들어 종료 시 취소에 씀. 담당(#215)이 정함
- #239 · 화면용 API 실행·의존성(D-042) 추가: fastapi·uvicorn 버전 고정, TestClient는 `httpx2`, 기본 바인딩 127.0.0.1. L3 담당이 정함(#239)

- #213 · SSH 라이브러리 asyncssh(D-041) 추가, SSH 도구(D-011) 메모에 원격 셸 해석을 막는 구체 방법(코드 상수 점검, 허용 문자 인자 검사, `-` 거부, `shlex.quote`)을 채움. 팀 합의(#213)
- #211 · 도구 구현 방식(D-023)을 후보에서 확정으로 옮김. MCP 서버 대신 파이썬 함수 도구 레지스트리를 Agents SDK 함수 도구로 감싸고, MCP 노출은 필요해지면 레지스트리 위에 얹는다. 팀 합의(#211)
- 2026-11-04 · Incident 분류 방법(D-027)과 L2 재분석 기준(D-028)을 담당자가 정함에서 확정으로 옮기고 L2 절을 만듦. 확신도 임계로 거르지 않고 기록만 하며, 저장 경쟁은 고른 Incident 한 줄 잠금으로 막는다(분류는 단계별 스레드라 Ticket끼리 경쟁이 없다). L2 담당이 정함
- #210 · 기본 LLM(D-009)을 Groq에서 Azure Foundry gpt-oss-120b로 바꿈. 설정만으로 Groq·Ollama로 되돌리는 구조 포함. 팀 합의(#210)
- #221 · L3 위협 시나리오 입력(D-029)을 담당자가 정함에서 확정으로 옮김, HTTP 클라이언트 httpx(D-039)와 데이터셋 MITRE ATT&CK Enterprise(D-040) 추가
- 2026-11-04 · Hunt 계약(#217): Hunt 계약과 `hunts` 테이블(마이그레이션 0002)을 추가하고, Ticket에 `hunt_id`(`origin = l3`이면 값, 그 밖에는 null, Hunt 하나에 Ticket 하나)를 더함. ID 접두사 `hnt`·`hrn` 추가, Agent Log hunt 대상 `subject_id`를 `hnt_`·`hrn_` ID로 좁힘. 공통 계약 변경이라 L1·L2·L3 담당자 전원의 승인이 필요하다
- #209 · 에이전트 프레임워크(D-022)와 에이전트 구조(D-024)를 후보에서 확정으로 옮김. 팀 합의(#209, L1·L2·L3 담당). 기본 LLM(D-009)·도구 구현 방식(D-023)·SSH 라이브러리·SSH 도구(D-011) 메모는 처음 쓰는 이슈에서 정한다
- 2026-11-03 · OCSF 정규화(D-007) 메모에 클래스별 공식 JSON Schema 검증을 정규화 이슈에서 반드시 한다고 덧붙임(#192)
- 2026-11-03 · 공통 데이터 계약(#192): Ticket 출처(D-026)를 확정으로 옮김, Ticket 생성 모드·ID·마이그레이션·Agent Log 저장·계약 라이브러리·생성 코드 린트 예외(D-033~D-038) 추가, 데이터 계약(D-003) 메모에 위치와 생성 도구 추가
- 2026-11-03 · 기점을 번호 기준(#191)으로 바꿈, SSH 도구(D-011)에 `-`로 시작하는 값 거부와 읽기 전용 원격 계정 추가
- 2026-11-03 · 하네스 적용 기점(2026-11-03, PR #191) 추가, SSH 도구(D-011)의 원격 셸 해석 내용 바로잡음
- 2026-11-03 · SIEM 설정 화면(D-021)에 `SIEM_` 접두사 제한과 화면 설정 우선을 추가, 결정 ID 표기 규칙 추가
- 2026-11-03 · D-011 결정, D-002·D-020·D-021 메모 보강, 폐기 절 추가, '결정 목록'으로 이름 바꿈
- 2026-11-03 · 결정 목록을 다시 정리함. D-001~D-021 확정, D-022~D-024 후보, D-025~D-031 담당자가 정함, D-032 추후
