---
issue: 326
date: 2026-11-17
owner: Pandyo
plan: 326-alert-normalize-skeleton.md
supersedes: []
---

# Alert 정규화 뼈대: 공통 구성·결과 품질 기록·폴백·헤더 마스킹

## 한 일

`mapping._alert`가 소스(suricata·modsecurity·guardduty·unknown)를 판별하고 Detection Finding(2004)을 공통 규칙으로 만든다. 생성 시각(`ocsf.time`)과 원 이벤트 시각(`start_time`)을 나누고, 엔티티는 ECS 표준 필드에서만 읽는다(센서 필드 제외). 결과 품질은 `normalize_status`의 `outcome`·`missing_fields`·`source`·`error_code`에 남는다. Kibana 알럿으로 읽을 수 없는 원본은 class 0 폴백 Alert로 저장돼 Ticket 분기까지 간다. 결과의 `ocsf`·`details`에서 Cookie·Set-Cookie·Authorization 값은 `[REDACTED]`가 된다. `python -m soc.normalize report`로 소스별 채움률을 본다. 소스별 매퍼는 이 뼈대에 붙는 후속 이슈다.

## 계획과 달라진 점

- **폴백 Alert의 `triage`는 정규화가 쓰지 않는다.** 계획은 "triage = pending으로 Ticket·L1을 지난다"였지만 `triage`는 정책 분기(`soc.l1.ticketing`)가 정한다(계약: 정규화 직후는 null). 폴백 Alert도 `triage = null`로 저장되고, 자동 모드면 Ticket이 만들어지고 시나리오 모드면 분기가 `pending`으로 표시한다. DB 테스트가 두 경우를 확인한다.
- **기존 DB 테스트 4건을 새 동작에 맞췄다.** `alert_without_title`은 이제 `failed`가 아니라 폴백으로 저장되므로, 실패·재시도를 보는 테스트(`test_normalize_db.py`)는 아직 실패하는 Event 샘플(`event_without_source`)로 바꿨다. 재시도 성공 테스트는 그 Event를 Base Event로 고쳐 읽는 방식으로 바꿨다. `alert_flat_keys`의 host 엔티티·host 자산 기대는 제거했다.
- **OCSF `analytic`의 `type_id`는 1(Rule)로 고정했다.** 공식 정의에서 필수이고 알럿은 SIEM 룰이 만든 것이라서다.
- **`threat.technique.id`가 문자열 하나여도 읽는다**(배열이 아닌 경우). 하위 기법(`T1059.007`)은 `technique.uid`가 상위 ID, `sub_technique.uid`가 전체 ID다.
- **생성 시각이 둘 다 있으면 `kibana.alert.start`가 이긴다.** 그 값이 읽을 수 없는 문자열이면 `@timestamp`로 넘어가지 않고 `bad_time` 폴백이다(계획의 "생성 시각을 읽을 수 없음").
- **로컬 검증 DB는 PostgreSQL 16이었다**(프로젝트 문서는 17). 마이그레이션과 DB 테스트는 16에서 통과했다.

## 다음 사람이 알아야 할 것

- **엔티티 변화.** Alert에서 `host.name` 엔티티가 사라졌고(수집기 컨테이너 ID였다), domain·url의 role이 `null`에서 `dst`로 바뀌었다. IP 형식의 domain 후보는 `type=ip`로 분류한다. host(target)·file_hash·process는 소스별 매퍼가 채워야 한다. 그 전까지 GuardDuty 알럿은 엔티티가 비고, ModSecurity는 목적지(`transaction.host_ip`)가 없다. Ticket 엔티티가 줄어 L2 묶음 근거가 그만큼 약하다.
- **Event 경로는 그대로다.** `ENTITY_FIELDS`(`host.name` 포함)는 Event만 쓴다. Event의 수집기 host 문제는 이 이슈 밖이다.
- **마스킹은 `mapping._finding` 끝에서 한 번 적용된다.** 이 뼈대는 헤더를 복사하지 않아 지금은 룰 설명처럼 복사된 문자열에만 닿는다. 소스별 매퍼가 `transaction.request.headers` 같은 값을 `details`나 `ocsf`에 복사해도 이 단계가 가린다. 줄 중간의 `Cookie:`와 `Proxy-Authorization`·`X-Auth-Token` 같은 다른 헤더 이름은 가리지 않는다(`mask.py`의 shortcut 주석). 에이전트의 원본 조회 도구에는 적용되지 않는다(별도 안건 후보).
- **`outcome`·`source`는 새 Alert 성공 행부터 채워진다.** 기존 행과 Event 행은 NULL이다. 채움률 점검은 NULL 행을 세지 않는다.
- **partial 판정 기준은 `rule_id`·`severity`·`original_time`뿐이다.** 틀린 IP는 `missing_fields`에만 기록되고 outcome을 `partial`로 바꾸지 않는다.
- **`soc.normalize.mapping`이 `soc.tools.local_intel`을 import한다.** 계획대로 `normalize_technique_id`를 재사용한 것인데, `soc.tools` 패키지가 에이전트 도구 레지스트리를 함께 끌어온다. 정규화 코드가 도구 패키지에 기대는 방향이라, 함수가 더 필요해지면 `soc.entities`처럼 가벼운 모듈로 옮기는 것이 낫다.
- **폴백 조건 밖의 실패.** JSON 손상(`_claim_batch`의 `json.loads`)은 여전히 배치를 멈춘다(D-050, `docs/notes/277-raw-original-text.md`). `escape_collision`·자산 조회·DB 오류는 `failed` + 재시도다.
- **Alert 계약 변경.** `ocsf.class_uid`가 2004 또는 0이다. PR에서 L1·L2·L3 담당자 승인을 받는다. `src/soc` 안에서 `class_uid == 2004`를 가정하는 소비 코드는 찾지 못했다.
- **OCSF 객체 정의 추가.** `analytic`, `attack`, `technique`, `tactic`, `sub_technique`, `observable`을 공식 1.9.0 정의에서 줄여 넣었다(`ocsf/SOURCE.md`). 정규화가 내보내지 않는 하위 객체(`related_analytics` 등)는 정의에 없어 내보내면 검사에서 실패한다.
- 정제 샘플 6개를 읽고 확인한 것(건수만): `event.module` 값 `suricata`·`modsecurity`, GuardDuty는 최상위 `guardduty` 키, `kibana.alert.uuid`와 `_id`가 6건 모두 같다. 샘플 원본은 커밋하지 않았고, 필요한 키만 손으로 줄인 `tests/fixtures/normalize/alert_skeleton.json`을 쓴다.
- 실제 ELK·실제 개발 DB의 알럿 15건 대조와 운영 규모 성능은 확인하지 못했다.

## 확인 방법

- `uv run pytest tests/normalize/test_alert_skeleton.py tests/test_contracts.py`: 소스 판별·공통 구성·폴백·마스킹·포트 붙은 domain 단위 테스트와 계약 샘플(class 0 Alert 포함).
- 임시 PostgreSQL(`DATABASE_URL`)에서 `uv run pytest -m db tests/normalize`: `test_alert_skeleton_db.py`가 `outcome`·`error_code`·`missing_fields`·`source` 기록, 이벤트의 NULL, 검증 실패 폴백, 일시 오류의 `failed` + 재시도, 폴백 Alert의 Ticket 분기(자동·시나리오), `report` 출력, CHECK 제약을 확인한다.
- `uv run python scripts/generate_contracts.py --check`, `cd frontend && pnpm contracts:check`: 생성 코드 일치.
- 마무리 전 검사(로컬 일회용 PostgreSQL 16, `-m "not llm and not qdrant and not embedder"`): 2,506 통과. 실패 3건·오류 1건은 실제 서비스가 필요한 `ssh`·`virustotal`·`elk` 마커 테스트(환경변수·서버 없음)와, 0108 추가 전에 돌려 목록이 모자랐던 `test_db_tables`(고친 뒤 `-m db`로 다시 돌려 통과)다. `uv run pytest -m db tests/test_db_tables.py tests/normalize`: 123 통과.
- `uv run ruff format --check .`, `uv run ruff check .`: 통과. `cd frontend && pnpm lint`(경고 1건은 기존), `pnpm build`, `pnpm test`(86 통과): 통과.
