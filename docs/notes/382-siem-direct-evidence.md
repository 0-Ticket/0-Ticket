---
issue: 382
date: 2026-11-26
owner: Juhyeok0603
plan: 382-siem-direct-evidence.md
supersedes: []
---

# 이벤트 정규화를 없애고 심에서 찾은 문서를 근거로 발급한다

## 한 일

이벤트 OCSF 정규화를 파이프라인에서 걷어냈다. `normalize()`는 `kind != "alert"`인 원본을
`validation_failed`로 거부하고, 이벤트 매핑표(클래스 표 7개·소스 표 2개)와 `event_tables.py`,
관련 테스트 862줄이 사라졌다. `[[ingest.sources]]`의 이벤트 대상 5개도 빠져서 더 이상
`logs-nginx.access-*` 같은 인덱스를 통째로 끌어오지 않는다. 알럿 정규화와 `mask_headers`·
`common.yaml`·`ecs_fields.yaml`은 그대로다.

대신 근거를 발급한다. `query_siem`이 모델에게 보인 히트마다 `siem_ref → (_index, _id)`를 도구
세션이 들고(`ToolSession.siem_refs`), 모델이 출력에 적은 `siem_ref`를 그 키 집합과 대조해 없는
값을 인용하면 run을 멈춘다. 통과한 것은 `AgentResult.cited_siem_refs`로 워커에게 가고,
`soc.evidence.issue`가 원문을 통째로 가져와 `raw_records` → `normalize_status(succeeded)` →
`events`(class 0)를 한 트랜잭션에 쓰고 `evt_` ID를 발급한다. 모델은 `get_raw`로 그 원문을 읽는다.

소스를 가리지 않는 심 조회 대상 `evidence`를 더했다(ECS 공통 필터·반환 필드만). `event.module`로
좁히면 한 소스만, 안 좁히면 전부 걸린다. 수리카타처럼 매핑표가 없던 소스도 이 경로로 근거가 된다.

도구 허용 목록은 단계가 아니라 태스크별이 됐다(D-084). `l2_classify`와 `l2_report`에는 심 조회와
`get_raw`를 주지 않는다 — 그 태스크가 인용해도 발급할 다음 태스크가 없다.

L1·L2·L3가 모두 발급을 부른다. L1은 판정 뒤, L2는 조사 뒤(보고 태스크의 허용 목록에 발급분을
더한다), L3는 검증 뒤(발급한 ID의 엔티티를 `record_entities`가 읽는다)다. 세 단계 모두 저장 전에
출력에서 `siem_refs`를 뗀다 — 발급 전 문서는 ID가 없어 저장하면 되돌릴 수 없는 포인터가 된다.

## 계획과 달라진 점

1. **L1 판정 모델의 출력 계약을 `l1_verdict`로 새로 뒀다.** 계획은 "L1 판정 출력 계약에 `siem_refs`를
   더한다"고 했는데, 그 계약이 `common/verdict.schema.json`이고 **저장하는 Verdict와 같은 파일**이었다.
   거기 더하면 `tickets.verdict`·`alerts.details.triage`에도 들어가고, 발급이 끝나면 근거는 `evt_`가
   되므로 저장된 `siem_refs`는 되돌릴 수 없는 포인터가 된다. 그래서 `contracts/l1_verdict.schema.json`을
   새로 만들어 출력에만 쓰고 저장 Verdict는 손대지 않았다.
   → **L1을 배선할 때 출력에서 `siem_refs`를 떼고 저장해야 한다.**
2. **계획 표의 `l3_hunt`는 코드에 없다.** 실제 태스크 이름은 `l3_hypothesize`다. `TASK_NAMES`
   일곱 개는 `l1_alert_triage`·`l1_ticket_judgment`·`l2_classify`·`l2_investigate`·`l2_report`·
   `l3_hypothesize`·`l3_verify`다.
3. **허용 목록은 태스크 키를 먼저 보고 없으면 단계 키를 본다.** 계획은 단계 키를 태스크 키로 바꾸라고만
   했다. 단계 키를 바로 없애면 `allowed`를 단계로 짜는 테스트 50곳이 깨진다. 배포 설정에는 단계 키를
   두지 않으므로 등록되지 않은 태스크는 도구가 하나도 붙지 않는다(기본 거부). **함정이 있다(아래).**
4. **`siem_ref` 위반에 새 실패 코드를 만들지 않고 `evidence_id_error`를 썼다.** 성질이 같고(근거 인용
   위반) 새 코드를 넣으면 보류·재시도 로직 전부에 손이 간다.
5. **`event_row`를 `src/soc/normalize/mapping.py`에 되돌렸다.** 이벤트 정규화 제거 때 함께 지워졌는데
   매핑표에 기대지 않는 순수 `events` 행 생성기이고, `dev_l1.py`·`hunt/dev_seed.py`와 발급 경로가 쓴다.
6. **`fetch_document`는 `{_index, _id, _source}` 세 칸만 돌려준다.** ELK의 `GET _doc` 응답에는
   `_version`·`found`가 더 있는데, 수집이 `original_text`에 넣는 모양과 같게 맞췄다.
   `serialize_original`을 그대로 쓸 수 있고 `get_raw`·`raw_detail`이 출처에 관계없이 같은 모양을 본다.
7. **`fetch_document`는 구체 인덱스만 받는다.** `_INDEX` 정규식은 쉼표·와일드카드를 허용하지만
   `_doc` 경로에는 쓸 수 없어 따로 막았다. 맵의 값은 늘 히트 하나의 `_index`라 문제없다.
8. **`common/types.schema.json`에 `siem_ref` 정의를 올렸다.** `raw_record.schema.json`에만 있던 서술을
   공용으로 옮기고 그쪽은 `$ref`로 바꿨다.
9. **`events.ocsf`에 `raw_data`를 넣지 않는다**(계획대로). 계획을 고쳤던 이유와 같다 — `ocsf`는 D-059
   마스킹 대상이라 담으면 불변 사본이 아니게 된다. 원문은 `raw_records.original_text`에만 있다.
10. **`AgentResult`의 칸 이름은 `cited_siem_refs`다.** 계획은 `siem_refs`라고만 적었다.
    `cited_evidence_ids`와 나란히 두려고 접두사를 붙였고, 담는 값도 세션 맵 전체가 아니라
    **인용이 검증된 것만**이다. 워커가 따로 거를 필요가 없다.
11. **읽기 역할에 `raw_records` 열 권한을 주는 마이그레이션 0310을 더했다.** 0003이 그 표를 명시적으로
    제외해 놔서 `get_raw`가 읽을 수 없었다. 준 열은 `id`·`kind`·`fetched_at`·`original_text`뿐이고
    `siem_ref`·`siem_profile`은 주지 않았다 — `siem_ref`에 인덱스 이름이 들어 있고, 모델에게 인덱스
    이름을 보이지 않는 것이 이 설계의 전제다. 계획의 "범위 밖"은 `raw_records` **스키마** 개편을
    말한 것이고, 권한 마이그레이션은 0007·0302와 같은 전례다.
12. **`l3_hypothesize`에는 발급을 붙이지 않았다.** 그 태스크는 근거를 전혀 인용하지 않는다
    (`cited_ids=_no_evidence`, 출력 계약 `hunt_hypotheses`에 근거 칸이 없다). 발급할 것이 없다.
13. **`query_records`를 `kind=alert`만 받도록 좁히지 않았다.** 발급된 class 0 Event가 `events`
    표에 있어 목록 조회가 여전히 쓸모 있다. 계획의 그 줄은 발급을 넣기 전 판단이다.
14. **발급 Event의 `source`는 `issued`다.** `normalize_status.source`는 이벤트 행에서 소문자·숫자·
    밑줄이어야 한다(0305). `outcome`은 비워 둔다 — 정규화 품질을 판단한 값이 아니다.
15. **`query_http_flow`·`summarize_http_flow`는 계획대로 지웠다**(`src/soc/tools/web.py` 삭제).
    한 번은 남겼다가 되돌렸다. 남긴 근거가 "검색 풀이 줄어 결과가 적어질 뿐"이었는데 **틀렸다**.
    그 둘은 `ocsf_class = 4002`로 거르고(`tools/web.py:60`) OCSF 경로 다섯 개를 읽는데, 발급분은
    class 0 Base Event이고 `evidence_ocsf()`가 쓰는 칸은 `class_uid`·`time`·`severity_id`·
    `message`·`metadata`뿐이다. 즉 발급된 근거는 그 둘에 **영원히 보이지 않고**, 이벤트 정규화가
    사라졌으니 4002 행도 더 생기지 않는다. 새 DB에서는 항상 빈 결과이고, 모델은 그것을
    "HTTP 활동이 없다"로 읽는다. 실제 로컬 실행에서 `query_http_flow`가 135회 불려 두 번째로 많이
    쓴 도구였고 전부 헛돌았다. HTTP 로그는 `query_siem`으로 찾고 발급된 근거는 `get_event`·
    `get_raw`로 읽는다. `tests/test_tools_db.py`의 그 도구 테스트 4개는 기존 4002 행과 새 class 0
    행을 `query_records`로 읽고 제거한 도구가 등록되지 않는지 확인하도록 바꿨다.
    기존 DB에 남은 4002 행을 읽을 길은 `query_records`의 `kind=event`다.

## 다음 사람이 알아야 할 것

### 아직 안 한 것

- **손으로 확인할 것 셋.** 기존 `evt_` 근거로 만든 과거 인시던트를 화면에서 열어 보기,
  서버의 심 조회가 실제로 200을 받는지, L2 라운드 소요 시간 전·후 측정.
- **공통 계약·설정 키 변경에 L1·L2·L3·UI 담당 확인**(원칙 7). 아래 "맞물리는 곳" 목록 그대로다.
- **`l3_hypothesize`는 발급하지 않는다.** 그 태스크의 출력 계약(`hunt_hypotheses`)에 근거 인용
  칸이 없고 `cited_ids`가 `_no_evidence`다. 심 조회 도구는 계획대로 그대로 뒀지만, 인용할 수
  없는 태스크에 로그 조회를 주는 것이 맞는지는 다시 볼 만하다(D-084의 논리를 그대로 적용하면
  빼는 쪽이다). 이번 이슈에서는 기존 동작을 바꾸지 않았다.
- **버린 건수를 남기는 범위.** L2는 보고 입력(`dropped_refs`)과
  `incidents.details.l2_analyze.dropped_refs`에 남긴다. L1·L3는 다음 태스크가 없어 경고 로그만
  남긴다(저장 Verdict·Hunt 모양을 바꾸지 않으려고).
- **`query_records`의 `kind` enum을 좁히지 않았다.** 계획의 "바꿀 곳"은 `("alert",)`로 줄이라고
  했지만, 발급된 class 0 Event가 `events` 표에 있으므로 목록 조회가 여전히 쓸모 있다. 사람이
  고른 "조회 도구 셋을 남긴다"와도 맞다. `query_http_flow`·`summarize_http_flow`와 달리 이쪽은
  발급분에도 값이 있다(`ocsf_class`·`summary`로 거른다). 그 둘은 계획대로 지웠다(위 15번).
- **`get_raw`에 `screen_input`이 걸리는지 따로 테스트하지 않았다.** `records` 도구 일반에 대해
  `tests/test_agent_input_redaction.py`가 이미 확인한다(`leak_records`). `get_raw`는 같은 경로를
  타는 또 하나의 `records` 도구라 중복 테스트를 만들지 않았다.

### 번호가 옮겨졌다

계획과 이슈 댓글은 이 이슈의 결정을 **D-081·D-082**, 읽기 권한 마이그레이션을 **0307**로 적었다.
그 사이 `origin/main`이 먼저 D-081(Incident 상세 화면, #385)·D-082(`incident_reviews`, #388)와
`0307_incident_reviews.sql`을 썼다. 그래서 이 브랜치의 것을 옮겼다.

| 계획·이슈의 표기 | 실제 |
|---|---|
| D-081 (근거 발급 방식) | **D-083** |
| D-082 (태스크별 허용 목록) | **D-084** |
| `0307_agent_reader_raw_records.sql` | **`0310_agent_reader_raw_records.sql`** (0308을 거쳐 두 번 옮겼다) |

`src/soc/db/migrate.py:89`가 같은 번호의 마이그레이션 둘을 `MigrationError`로 거부하므로, 옮기지
않으면 병합한 순간 모든 db 테스트가 깨진다. 참조 46곳을 함께 고쳤다. 계획 파일의 표기도 바꿨다
(원칙 8의 "고쳐 쓰지 않는다"는 내용 변경을 말하고, 이것은 같은 결정의 번호를 맞춘 것이다).

두 번째로 옮겼다. `origin/main`을 다시 합칠 때 #389가 `0308_attack_actors.sql`과
`0309_agent_reader_attack_actors.sql`을 이미 써서 `0308`이 또 겹쳤다. 이 이슈의 것을
**`0310_agent_reader_raw_records.sql`**으로 옮겼다. D-083·D-084는 그대로다(#389는 D 번호를
쓰지 않았다). 번호만 바꿨고 내용은 그대로다.

**브랜치는 병합 뒤 `origin/main`과 같은 지점에서 앞서 있다**(뒤처짐 0). main의 4커밋이
`docs/decisions.md`·`tests/test_db_tables.py`에서 충돌했고 둘 다 양쪽을 살려 해결했다.

### 함정

- **허용 목록의 단계 키 폴백.** 배포 설정에는 태스크 키만 있으므로, **배포 설정을 불러와
  `allowed["l3"]`를 덮어쓰는 테스트는 조용히 무시된다**(태스크 키가 이미 있어서 그쪽이 이긴다).
  `tests/test_l3_hunt_db.py`·`test_l3_hunt_worker_db.py`가 그래서 깨졌고 태스크 키를 쓰도록 고쳤다.
  비슷한 테스트를 새로 쓸 때는 태스크 키로 덮어써야 한다.
- **`normalize_status`를 빼면 Event가 두 개 생긴다.** `src/soc/normalize/store.py`가
  `normalize_status` 행이 없는 `raw_records`를 자동으로 pending으로 집어간다. 발급이 그 행을
  `succeeded`로 쓰는 이유다. `test_evidence_issue_db.py`의
  `test_the_normalizer_does_not_make_a_second_event_from_the_issued_original`이 이것을 지킨다.
- **셸 heredoc이 백슬래시를 하나 먹는다.** 테스트에 `'q"b\\s\x01z한글'` 같은 소스를 넣을 때
  heredoc으로 쓰면 `\s`로 줄어 `SyntaxWarning`이 난다. 파일을 읽어 줄 단위로 바꾸거나 `chr(92)`로
  만든다.
- **계약을 고치면 세 곳을 같이 고친다.** `contracts/*.json` → `uv run python
  scripts/generate_contracts.py` → `tests/contract_samples.py`의 `CONTRACT_NAMES`(별도 목록)와
  `tests/fixtures/contracts/{valid,invalid}/<이름>.json` 샘플.
- **열 단위 GRANT는 `count(*)`를 막지 못한다.** 0310을 넣자
  `test_reader_role_is_denied_elsewhere`의 `SELECT count(*) FROM raw_records`가 통과해 버렸다.
  주지 않은 열(`siem_ref`·`siem_profile`)로 단정을 바꿨다.
- **발급은 `GET /<index>/_doc/<id>`가 요청한 것과 같은 `_index`·`_id`를 돌려준다고 전제한다.**
  `evidence_rows`가 응답의 두 값으로 저장 키를 다시 만들기 때문이다. 구체 인덱스로 부르므로
  ELK는 같은 값을 준다. 혹시 다르면 같은 문서가 두 키로 저장돼 중복이 생길 수 있다(손상은
  아니다). 방어 코드는 넣지 않았다 — 일어날 수 없는 경우다.
- **이벤트 수집을 끊으면 파이프 e2e 테스트의 건수가 바뀐다.** `test_pipeline_db.py`·
  `test_lab_cycle_db.py`에서 이벤트 원본 5건이 `validation_failed`로 남고 `events`는 0이다.
  그것이 새 기대값이다.

### 맞물리는 곳 (원칙 7, PR 전 확인 필요)

- `[tools.allowed]`가 단계 3개 키에서 태스크 7개 키로 바뀌었다. L1·L2·L3가 전부 쓴다.
- 새 계약 이름 `l1_verdict`. 저장 Verdict는 바뀌지 않았다.
- `AgentTask.cited_refs`(선택)와 `AgentResult.cited_siem_refs`가 생겼다.
- `CallContext.siem_docs`(호출별)와 `ToolSession.siem_refs`(실행별)가 생겼다.
- `ToolRegistry.session()`이 `task` 인자를 받는다(선택).
- 새 도구 `get_raw`와 새 심 조회 대상 `evidence`.
- 마이그레이션 0310이 읽기 역할에 `raw_records` 네 열을 준다.
- `events`에 class 0 원문 포인터 행이 들어온다. 기존 정규화 행과 섞인다.
- `normalize_status`에 정규화기가 아닌 코드가 `succeeded` 행을 쓴다.
- `normalize()`가 이벤트 원본을 거부한다.

## 확인 방법

```
uv run ruff format --check .   통과
uv run ruff check .            통과
uv run pytest                  2599 passed, 718 deselected
uv run pytest -m "db or qdrant"  (아래 참고. postgres·qdrant를 띄우고 돌렸다)
```

db 마커는 `docker compose up -d postgres` 뒤에 돌렸다. 주요 테스트:

- `tests/test_tools_siem.py` 131건 — 맵 5건, 원문 가져오기 9건, `evidence` 대상 6건
- `tests/test_agent_siem_refs.py` 6건 — 인용 검증
- `tests/test_agent_task_tools.py` 8건 — 태스크별 허용 목록
- `tests/test_tools_get_raw.py` 7건 — 스펙 모양과 허용 목록
- `tests/test_evidence_issue.py` 30건 — 행 만들기(DB 없음)
- `tests/test_evidence_issue_db.py` 8건(db) — 트랜잭션, 중복 방지, 정규화기와의 분리
- `tests/test_tools_db.py` 46건(db) — `get_raw` 실제 읽기와 열 권한
- `tests/l1/test_l1_judge_db.py` 28건(db) — L1 판정과 발급
- `tests/test_l3_hunt_db.py` 30건(db) — L3 검증과 발급
- `tests/test_lab_cycle_db.py`·`tests/test_pipeline_db.py` 9건(db) — 알럿만 정규화되는 전체 흐름

db·qdrant는 `docker compose up -d postgres qdrant` 뒤 `QDRANT_URL=http://127.0.0.1:6333`으로
돌렸다. `.env`에 `QDRANT_URL`이 비어 있어서 그 값을 셸에서 넣어야 했다.

ELK 마커 테스트와 서버 확인은 하지 않았다. 실제 심 조회가 200을 받는지도 확인하지 않았다.
