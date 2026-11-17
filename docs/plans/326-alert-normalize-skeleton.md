---
issue: 326
date: 2026-11-17
owner: Pandyo
supersedes: [302-destination-ip.md]
---

# Alert 정규화 뼈대

`supersedes`는 302 계획의 "새로운 IP 검증 정책" 범위 밖 항목만 대체한다. 목적지 IP 보존 방식은 그대로다.

## 목표

`raw_records`(kind=alert)의 Elastic 알럿 원본을 소스와 관계없는 공통 규칙으로 OCSF 1.9.0 Detection Finding(2004)과 Alert 행으로 만든다. 소스를 판별하고, 결과 품질을 `normalize_status`에 기록하고, 해석할 수 없는 원본도 class 0 폴백 Alert로 남기고, 민감 헤더를 마스킹한다. 소스별 매퍼(Suricata·ModSecurity, GuardDuty)는 후속 이슈다.

## 방법

0. **선행:** 사람이 정제한 대표 샘플 5종(룰 5종, 문서용 IP·쿠키·ID 제거)을 받는다. 받기 전에는 소스 판별 테스트의 입력을 만들지 않는다. 받은 샘플은 `tests/fixtures/normalize/`에 손으로 다시 쓴 작은 파일로 둔다(실제 원본을 그대로 커밋하지 않는다).
1. **샘플과 테스트 먼저.** 소스별(suricata, modsecurity, guardduty, unknown) 정상 샘플과 폴백 샘플을 만들고, 기대 결과와 함께 실패하는 테스트를 먼저 쓴다.
2. **값 읽기.** 기존 `mapping._value`·`_text`(점 키 우선, 없으면 중첩 경로)를 그대로 쓰고, Alert 매핑은 이 함수로만 값을 읽는다.
3. **소스 판별** (`_detect_source`). `event.module`이 `suricata`면 suricata, `modsecurity`면 modsecurity. 없으면 `kibana.alert.original_event.module`로 같은 판별. 그것도 없고 최상위 키 `guardduty`가 있으면 guardduty. 그 밖에는 `unknown`이고 오류가 아니다.
4. **공통 구성.**

   | OCSF | 값 |
   |---|---|
   | `category_uid`/`class_uid`/`activity_id`/`type_uid` | 2 / 2004 / 1 / 200401 |
   | `is_alert`, `status_id` | true, 1(New) |
   | `time`, `finding_info.created_time` | `kibana.alert.start`, 없으면 `@timestamp`(UTC epoch ms) |
   | `start_time`, `end_time` | `kibana.alert.original_time`, 없거나 읽을 수 없으면 `time` |
   | `severity_id` | `kibana.alert.severity`: low 2, medium 3, high 4, critical 5, 없음·그 외 0 |
   | `finding_info.uid` | `kibana.alert.uuid`, 없으면 hit `_id` |
   | `finding_info.title`, `desc` | `kibana.alert.rule.name`, `kibana.alert.rule.description` |
   | `finding_info.analytic` | 이름 = 룰 이름, uid = `kibana.alert.rule.rule_id`(없으면 생략). 필수 속성(`type_id` 등)은 공식 정의로 확인해 채운다 |
   | `finding_info.attacks` | `kibana.alert.rule.tags`의 `attack.T####`를 `soc.tools.local_intel.normalize_technique_id`로 검증한 것만. 없으면 생략 |
   | `risk_score` | `kibana.alert.risk_score`를 반올림한 정수. 없으면 생략 |
   | `message` | 룰 설명, 없으면 title. `kibana.alert.reason`은 쓰지 않는다 |
   | `metadata` | 현재 값 유지(버전 1.9.0, 제품 Elasticsearch/Elastic) |
   | `unmapped` | 비워 둔다. 원본 전체 복사 없음 |
   | `observables` | 엔티티 목록에서 만든다(type_id 매핑은 공식 정의 기준) |
   | 기존 `evidences[].dst_endpoint.ip` | 그대로 둔다(302) |

5. **Alert 계약 바로가기 필드.** `time` = `ocsf.start_time`(원 이벤트 시각, `ocsf.time`과 다르다), `severity` = `severity_id`, `title` = `finding_info.title`, `rule_id` = `kibana.alert.rule.rule_id`(없으면 null), `entities` = 아래 규칙, `details` = 소스 고유 값(마스킹 후). `details`에는 `source`를 넣지 않는다(소스는 `normalize_status.source`에 둔다).
6. **엔티티(Alert 전용, Event는 건드리지 않는다).** ECS 표준 필드만 읽는다. `source.ip` → ip/src, `destination.ip` → ip/dst, `user.name` → user/actor, `url.domain` → domain/dst, `url.original` → url/dst. `host.name`, `agent.*`는 엔티티로 만들지 않는다. host(target)·file_hash·process는 소스별 매퍼가 채운다. IP는 `ipaddress`로 형식을 검증하고, 틀리면 엔티티에 넣지 않고 `missing_fields`에 해당 OCSF 경로(`evidences[].src_endpoint.ip`, `evidences[].dst_endpoint.ip`)를 기록한다. 값은 원본 문자열 그대로 둔다. Event의 `ENTITY_FIELDS` 경로는 그대로다.
7. **결과 품질(`outcome`).**
   - `ok`: 알려진 소스이고 아래 partial 기준에 걸리지 않는다.
   - `partial`: 2004를 유지하고, `unknown_source`이거나 `rule_id`·`severity`·`original_time` 중 확보하지 못한 것이 있다. `missing_fields`에는 OCSF 경로로 적는다(`finding_info.analytic.uid`, `severity_id`, `start_time`). 알 수 없는 소스면 `error_code = unknown_source`다. 소스는 알지만 필드만 빠졌으면 `error_code`는 비운다.
   - `fallback`: class 0 폴백 Alert(아래).
8. **폴백 Base Event.** 아래 사유일 때만 class 0으로 내리고 Alert는 반드시 남긴다. 값을 지어내지 않는다.
   - 사유 코드: `invalid_source`(`_source`가 없거나 객체가 아님), `missing_uid`(`kibana.alert.uuid`와 `_id` 모두 없음), `missing_title`(룰 이름 없음), `bad_time`(생성 시각을 읽을 수 없음), `validation_failed`(우리 매핑 결과가 OCSF·계약 검증에서 떨어짐).
   - `class_uid`/`category_uid`/`activity_id`/`type_uid`/`severity_id` = 0, `time` = 원본 `@timestamp`, 읽을 수 없으면 `raw_records.fetched_at`(대체했으면 `details.fallback.time_from = "fetched_at"`), `message` = 알럿 제목(Alert `title`) = `정규화 실패: <사유 코드>`, `rule_id` = null, `entities` = [], `severity` = 0, `triage` = `pending`(기존 정책 분기 그대로 Ticket·L1을 거친다), `details.fallback.reason`에 사유 코드.
   - DB·자산 조회 같은 일시 오류(`asset_lookup_failed`, `db_error`)와 Event의 정규화 실패는 지금처럼 `failed` + 재시도다.
   - JSON 손상(`json.loads` 실패)은 이번 범위 밖이다(D-050 알려진 한계, `docs/notes/277-raw-original-text.md`).
9. **상수 목록.** `errors.py`의 `FAILURES`는 그대로 두고, `PARTIAL_REASONS = ("unknown_source",)`와 `FALLBACK_REASONS`(위 5개)를 별도 상수로 둔다. 구분 기준은 `outcome`이다.
10. **DB.** 마이그레이션 `0108_normalize_outcome.sql`: `normalize_status`에 `outcome text CHECK (outcome IN ('ok','partial','fallback'))`(nullable), `missing_fields text[] NOT NULL DEFAULT '{}'`, `source text CHECK (source IN ('suricata','modsecurity','guardduty','unknown'))`(nullable)를 더한다. 기존 행과 Event 행은 `outcome`·`source`가 NULL이다. `status`의 의미와 CHECK는 바꾸지 않는다. `_MARK_SUCCEEDED`가 `error_code`·`outcome`·`missing_fields`·`source`를 쓰고(지금은 `error_code`를 지운다), `result_kind`/`result_id`는 폴백 Alert도 가리킨다. `Result`와 `save_success`에 이 값들을 실어 나른다. `RawRow`에 `fetched_at`을 더하고 `_claim_batch`가 읽는다.
11. **마스킹** (`src/soc/normalize/mask.py`). Alert 결과의 `ocsf`·`details`를 만든 마지막 단계에 적용해 소스별 매퍼가 빠뜨리지 못하게 한다. dict 키가 `cookie`·`set-cookie`·`authorization`(대소문자 무시)이면 값을 `[REDACTED]`로 바꾼다. 문자열 값은 줄 시작이 `Cookie:`·`Set-Cookie:`·`Authorization:`(대소문자 무시)인 줄의 값 부분을 가린다. 입력은 바꾸지 않고 새 값을 돌려준다. `raw_records.original_text`는 바꾸지 않는다. 에이전트의 원본 조회 도구에 같은 마스킹이 필요한지는 이번 범위 밖의 별도 안건 후보다.
12. **Alert 계약.** `contracts/alert.schema.json`의 `ocsf.class_uid`를 `const 2004`에서 `enum [2004, 0]`으로 넓히고 `uv run python scripts/generate_contracts.py`로 Python·TS를 다시 만든다(생성 코드는 직접 고치지 않는다). `tests/fixtures/contracts/`에 class 0 Alert 샘플과 잘못된 class_uid 샘플을 더한다.
13. **소스별 채움률 점검.** `uv run python -m soc.normalize report`를 더한다. `normalize_status`만 읽는 읽기 전용 명령이며 소스별로 총 건수, `outcome`별 건수, `missing_fields` 항목별 누락 건수를 한 줄씩 낸다(건수만, 원문 없음). 기본 실행(`python -m soc.normalize`)은 바뀌지 않는다.
14. 기존 정규화 테스트와 fixture(`tests/fixtures/normalize/raw.json`의 `host.name` 엔티티, `alert_without_title` 기대)를 새 규칙에 맞게 고친다.

## 바꿀 곳

- `src/soc/normalize/mapping.py`: Alert 매핑(소스 판별, 공통 구성, 엔티티, 폴백), `Result`·`RawRow` 확장
- `src/soc/normalize/mask.py`: 새 파일(마스킹)
- `src/soc/normalize/errors.py`: `PARTIAL_REASONS`, `FALLBACK_REASONS`
- `src/soc/normalize/run.py`: 검증 실패 시 Alert 폴백, 결과 품질 전달
- `src/soc/normalize/store.py`: `_claim_batch`의 `fetched_at`, `_MARK_SUCCEEDED`·`save_success`의 새 칸
- `src/soc/normalize/__main__.py`: `report` 하위 명령
- `src/soc/normalize/ocsf/objects.json`, `src/soc/normalize/ocsf/SOURCE.md`: `analytic`, `attacks`(attack·technique 등), `observables` 공식 1.9.0 정의를 #302 방식으로 줄여 넣고 출처 기록
- `src/soc/db/migrations/0108_normalize_outcome.sql`: 새 파일
- `contracts/alert.schema.json`, `src/soc/contracts/generated/`, `frontend/src/api/generated/`: 계약과 생성 코드
- `tests/fixtures/normalize/`, `tests/fixtures/contracts/`, `tests/normalize/`, `tests/test_contracts.py`: 샘플·테스트
- `docs/decisions.md`: D-059, `docs/notes/326-alert-normalize-skeleton.md`: 개발 기록

## 다른 코드와 맞물리는 곳

- **Alert 계약 변경(공통 계약).** `ocsf.class_uid`가 2004 또는 0이 된다. 이 PR에서 L1·L2·L3 담당자 승인을 받는다. `src/soc` 안에서 `class_uid == 2004`를 가정하는 소비 코드는 계획 단계 검색에서 찾지 못했다(개발 때 다시 확인).
- **Alert 엔티티 변경.** `host.name` 엔티티가 사라지고, domain·url의 role이 `null`에서 `dst`로 바뀐다. 읽는 곳은 자산 조회, Ticket 엔티티, L2 그래프, `l3/hunt/verify.py`, `tools/similar_cases.py`다. 인시던트 묶음 담당자와 role 변경은 맞췄다고 사람이 확인했다.
- **`normalize_status` 칸 추가.** `outcome`·`missing_fields`·`source`를 더한다(기존 칸 의미 불변). `error_code`가 `succeeded` 행에도 채워진다. `api/ui_read.py`는 Alert가 없는 행에서만 `error_code`를 읽으므로 영향이 없다.
- **폴백 Alert.** `triage = pending`으로 저장돼 자동 모드에서 Ticket이 만들어지고 L1이 받는다. 근거가 없어 L1은 보류할 것으로 보이며(D-025), 이 흐름을 DB 테스트로 확인한다.
- Event 정규화 경로, `ENTITY_FIELDS`, 에이전트 도구, API, 화면은 바꾸지 않는다.

## 범위 밖

- 소스별 매퍼(Suricata·ModSecurity, GuardDuty)와 host(target)·file_hash·process 엔티티
- JSON 손상 원본의 폴백 처리(`store._claim_batch`의 `json.loads`가 배치를 멈추는 한계, D-050)
- 에이전트의 원본 로그 조회 도구에 같은 마스킹 적용(별도 안건 후보)
- Event의 `host.name` 엔티티 문제
- 기존 `alerts` 행의 소급 재정규화, 실제 ELK·LLM 호출, 새 환경변수·라이브러리

## 완료 기준

- [ ] 대표 원본 5종(룰 5종)의 정제 샘플로 소스 판별이 맞게 동작한다(suricata, modsecurity, guardduty, unknown).
- [ ] 점 표기 키와 중첩 경로 둘 다 읽는다.
- [ ] `class_uid` 2004, `type_uid` 200401, `is_alert` true, `status_id` 1이 들어간다.
- [ ] `ocsf.time`은 생성 시각, `start_time`·`end_time`은 원 이벤트 시각이고, Alert 계약의 `time`은 `start_time`과 같다.
- [ ] 심각도 매핑이 표대로 동작하고 없으면 0이다.
- [ ] `rule_id`가 `kibana.alert.rule.rule_id`로 채워지고 없으면 null이다.
- [ ] `finding_uid`는 `kibana.alert.uuid`를 우선 쓰고 없으면 `_id`를 쓴다.
- [ ] 센서 필드(`host.name`, `agent.*`)가 엔티티에 들어가지 않고, 틀린 IP는 엔티티에 들어가지 않고 `missing_fields`에 기록된다.
- [ ] 알 수 없는 소스는 2004 + `partial` + `unknown_source`로 저장된다.
- [ ] 해석 불가 원본(`invalid_source`, `missing_uid`, `missing_title`, `bad_time`, 매핑 결과의 검증 실패)은 class 0 폴백 Alert로 저장되고 `fallback`과 사유가 기록된다. 폴백 Alert가 `triage = pending`으로 Ticket·L1 경로를 지나는 DB 테스트가 있다.
- [ ] 일시 오류(자산 조회, DB)는 `failed` + 재시도로 남는다.
- [ ] 기록된 `outcome`·`error_code`·`missing_fields`·`source`를 조회할 수 있고 기존·Event 행은 NULL이다.
- [ ] 민감 헤더가 `ocsf`·`details`에서 마스킹되고(dict 키 대소문자 무시, `Name: value` 줄) 원본 테이블은 그대로다.
- [ ] `python -m soc.normalize report`로 소스별 채움률을 볼 수 있다.
- [ ] Alert 계약(2004 또는 0)과 생성 코드가 맞고 `scripts/generate_contracts.py --check`가 통과한다. L1·L2·L3 담당자 승인을 PR에서 받는다.
- [ ] 결정 대장에 time 규칙, rule_id 규칙, 엔티티 role 규칙을 기록한다(D-059).
- [ ] DB 테스트는 `db` 마커로 나눈다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과, 임시 PostgreSQL에서 `uv run pytest -m db` 통과.
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록.

## 토론으로 정한 것

- **폴백과 계약.** Alert 계약의 `ocsf.class_uid`를 2004 또는 0으로 넓힌다(선택지 A). 대안은 폴백도 class 2004로 두는 것이었다. 공통 계약 변경이라 PR에서 L1·L2·L3 담당자 승인을 받는다.
- **샘플.** 사람이 정제한 샘플을 첨부한다. 확인된 값: 소스 이름은 suricata/modsecurity/guardduty/unknown, `event.module` 실제 값은 `suricata`·`modsecurity`, GuardDuty는 `event.module` 없이 최상위 `guardduty` 키로 판별, ModSecurity의 Cookie는 `transaction.request.headers`의 객체 키 `Cookie`(문자열 값).
- **uuid.** 이슈 본문의 "uuid 없으면 폴백"을 정정한다. `kibana.alert.uuid`를 우선, 없으면 `_id`, 둘 다 없을 때만 폴백한다. 확인한 샘플에서 두 값이 같았다.
- **title·시각 없음.** 폴백(class 0)으로 내리고 사유 `missing_title`·`bad_time`을 남긴다. 우리 매핑 결과가 OCSF·계약 검증에서 떨어지는 경우는 재시도해도 같으므로 폴백(`validation_failed`)으로 보낸다. 일시 오류만 `failed` + 재시도를 유지한다.
- **엔티티.** ECS 표준 필드만 읽고 `host.name`을 제거한다. host(target)는 소스별 매퍼가 채운다. Event는 건드리지 않는다. 묶음 담당자와 role 변경(domain·url `null` → `dst`)은 맞췄다.
- **저장.** `outcome`은 nullable + CHECK(ok, partial, fallback), 기존 행·Event 행은 NULL(이 이슈는 Alert만 측정하므로 거짓 `ok`를 만들지 않는다). `source` 컬럼을 `normalize_status`에 더한다.
- **마스킹.** 정규화 안에 작은 마스킹 함수를 둔다. D-048 에이전트 가림 함수는 쓰지 않는다(Cookie 규칙이 없고 단계 분리 원칙).
- **빈칸 답변.** `missing_fields`는 OCSF 경로. partial 기준은 `rule_id`·`severity`·`original_time` 중 확보하지 못한 것. `error_code`는 `FAILURES`와 별도 상수 목록. `unmapped`는 비움, `metadata`는 현재 값 유지, 마이그레이션은 0108. JSON 손상은 범위 밖으로 후속 메모. IP 형식 검사는 #302의 범위 밖 항목을 이 계획이 대체한다. `risk_score`는 반올림 정수. ATT&CK ID 검증은 `normalize_technique_id` 재사용. OCSF 객체 정의는 #302 방식으로 추가하고 `SOURCE.md`에 출처를 적는다.
- **계획 작성 때 위 답변을 적용하며 채운 해석(개발 전에 사람이 다르게 정하면 "바뀐 점"에 적는다).** (a) 생성 시각이 없거나 읽을 수 없으면 `bad_time`, `original_time`이 없거나 읽을 수 없으면 폴백이 아니라 `partial`이다. (b) 틀린 IP는 `missing_fields`에만 기록하고 `partial` 기준은 아니다. (c) 소스는 알지만 필드만 빠진 `partial`의 `error_code`는 비운다. (d) 폴백 Alert의 `source`는 `unknown`이다. (e) 채움률 점검 명령은 `python -m soc.normalize report`이고 건수만 낸다. (f) 폴백 Alert의 `title`은 `message`와 같은 `정규화 실패: <사유 코드>`다.
- 결정 대장에 D-059를 추가한다.

## 바뀐 점
