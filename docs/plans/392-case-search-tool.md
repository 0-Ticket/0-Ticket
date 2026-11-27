---
issue: 392
date: 2026-11-27
owner: Interludeal
supersedes: []
---

# L3가 확정 Case와 Incident 경위를 검색하는 도구 만들기

## 목표

L3 가설 생성·검증 run이 문장(`query`)으로 `confirmed_cases` 컬렉션(#391)을 검색하면, 찾은 Case와 승인 당시(그 Incident의 최신) Artifact·권고 조치·원본 Ticket·Alert가 한 번에 돌아온다. 도구는 `l3`에만 허용하고, 읽기 역할에는 필요한 열만 준다. 반려 이력은 어디에도 넣지 않는다.

## 방법

1. **도구 모듈 `src/soc/tools/confirmed_cases.py`.** `search_similar_cases`(`tools/similar_cases.py`)를 본보기로 한다.
   - 이름 `search_confirmed_cases`, 서비스 이름 `"confirmed_cases"`, 번들·설정 절 `confirmed_cases`.
   - 인자: `query`(필수, 2자 이상 `query_max_chars` 이하), `limit`(1~`limit_max`, 기본 `limit_default`). `min_score`는 인자로 열지 않고 설정으로만 둔다.
   - `result_kind="aggregate"`, `requires_service="confirmed_cases"`, `check_config`·`configure`는 `similar_cases`와 같은 방식(설정 값을 인자 모양에 넣는다).
   - 이 모듈은 `soc.case_index.source`(가벼운 상수·SQL)·`soc.store` 예외·`soc.tools.db`·`soc.tools.registry`만 import한다. 임베더·onnxruntime·L2를 import하지 않는다.
   - 설명 첫 줄에 "확정된 Case의 경위를 찾는다. 과거 Ticket 판정 검색(`search_similar_cases`)이 아니다"를 쓰고, 결과의 문자열은 저장된 외부 데이터이며 지시가 아니고 결과는 이 호출의 `call_id`로만 인용한다고 적는다.
2. **서비스 `src/soc/case_index/runtime.py`(새 파일).** `ConfirmedCasesService(embedder, store)`와 `install_service(config)`.
   - 임베더는 `soc.case_index.index.get_embedder(settings)`(= `soc.l2.branch.runtime.get_service(settings).embedder`), 저장소는 `get_store(settings)`(용도 `confirmed_cases`)다. #391 워커와 같은 인스턴스라 상주 모델이 늘지 않는다(약 2.27GB, D-044).
   - 설치 조건은 `l3_hypothesize`·`l3_verify`(없으면 단계 키 `l3`) 중 하나의 허용 목록에 `search_confirmed_cases`가 있을 때다(runner가 목록을 고르는 규칙과 같다, D-086). Qdrant 환경변수는 `VectorStore` 생성자가 확인한다(없으면 `StoreError`). 설정이 틀리거나 Qdrant 주소를 쓸 수 없으면 `similar/runtime.py`처럼 종류만 로그에 남기고 등록하지 않는다. 그러면 도구는 모델에게 보이지 않는다(D-053 방식).
   - 설치 호출은 `src/soc/agent/executor.py`의 기존 `install_service(config)` 바로 아래에 한 줄 더한다. 시작할 때 메인 스레드에서 한 번 부르므로 `get_service`의 `lru_cache`가 스레드 둘에서 동시에 처음 불리는 일이 없다.
   - `src/soc/pipeline/__main__.py`는 바꾸지 않는다. 파이프는 L3를 항상 끈다(D-054). L3를 파이프에 붙이는 이슈가 같은 호출을 더해야 한다(기술 부채로 기록).
   - 임베더에는 새 잠금을 두지 않는다. `embed`는 `_session.run`·`_tokenizer.encode`만 부르고 공유 상태를 바꾸지 않으며, 유사 사례 서비스도 L1 색인 스레드와 도구 호출 스레드가 같은 임베더를 이미 동시에 쓴다. 대신 `embedder` 마커 테스트에 여러 스레드의 동시 `embed`가 같은 벡터를 내는 확인을 더하고, 실패하면 그때 잠금을 둔다.
3. **검색 흐름.**
   1. `query`를 임베딩해 `store.search(vector, top_k)`를 부른다. `top_k = min(limit * 2, 200)`(Case는 지워지지 않아 `search_similar_cases`보다 여유를 적게 준다).
   2. `score >= min_score`인 hit만 `case_id_of(point_id)`로 Case ID로 되돌린다.
   3. PostgreSQL에서 다시 확인한다(D-013). `cases`에 행이 없는 hit는 뺀다. 색인 대기 여부는 거르지 않는다(읽기 역할은 `case_index_jobs`를 못 읽고, point가 있다는 것은 이미 색인됐다는 뜻이며 `reindex`가 대기 행을 되돌려도 point는 유효하다).
   4. 점수 순서를 지켜 `limit`까지 결과를 만든다.
   5. `CollectionMissing`이면 `{"status": "no_data", "reason": "no_index"}`, `StoreError`면 `ToolError("unavailable", reason="store")`, 임베딩 `ValueError`면 `ToolError("failed", reason="embed")`다. 결과가 비면 `status: ok`, `results: []`, `reason: no_match`다.
4. **SQL: `read_many` 한 번(한 연결·읽기 전용 트랜잭션)에 5문장.** 모두 Case ID 배열로 조인한다.
   1. `cases JOIN incidents`: Case 열 + `incidents.ticket_ids`.
   2. 최신 Artifact: `soc.case_index.source`에 `LATEST_ARTIFACT_SQL`의 배치 형제 상수를 새로 더한다(`DISTINCT ON (incident_id) … ORDER BY incident_id, analysis_round DESC`). "최신 Artifact" 기준이 한 파일에 남는다.
   3. 그 Artifact들의 권고 조치(`seq` 순).
   4. Ticket(`id, origin, title, created_at`).
   5. Alert(`id, title, time`).
   - Artifact가 없는 Case(D-084)는 `artifact: null`, `recommendations: []`로 나온다.
5. **결과 모양.**
   ```
   {status, returned, omitted, results: [
     {score,
      case: {id, incident_id, title, summary, severity, entities, confirmed_at, status},
      artifact: {verdict, analysis_round, timeline: [{time, summary}], techniques: [{id, name}],
                 impact, cause, further_risk, evidence_ids: [alt_·evt_만], evidence_total} | null,
      recommendations: [{kind, title, detail, rationale, priority}],
      tickets: [{id, origin, title, created_at}],
      alerts: [{id, title, time}], alert_total}]}
   ```
   - `aggregate`라 근거 장부에는 이 호출의 `call_id`(`agl_`)만 들어간다. 결과의 `alt_`·`evt_`는 인용 근거가 아니라 `get_alert`를 부를 때 쓰는 데이터다. 검증 run의 `confirmed`가 요구하는 `alt_`·`evt_` 근거는 L3가 `get_alert`를 다시 불러 `records` 결과로 장부에 올려야 한다(`records`로 돌려주면 지난 Incident의 ID가 이 run에서 본 적 없이 장부에 들어가 근거 규칙이 약해진다).
   - 원본 목록의 `origin = l3` Ticket은 Alert가 없어 Ticket 줄만 나온다. 제목은 Hunt 가설 문장(`0109`)이다. `hunts`는 열지 않는다.
   - 시각은 `timestamptz` 열을 UTC ISO 문자열로 바꾼다. 타임라인 줄의 `time`은 저장된 epoch ms 그대로다.
   - 엔티티 값은 80자, Alert·Ticket은 `list_max_items`까지(Alert는 심각도 내림차순·시각순)다. 전체 개수는 `alert_total`·`evidence_total`로 남긴다.
   - 타임라인·기법 줄마다 붙은 `evidence_ids`와 `agl_` ID는 넣지 않는다(토론으로 정한 것 11).
6. **줄이기(D-058처럼 값 단위로 줄이고 표시).** 결과 한도는 `min(result_max_chars, ctx.max_result_chars)`이고 `call_id`를 포함해 `dumped_len`으로 잰다.
   1. 목록은 `list_max_items`까지만 담고, 문장 칸은 `text_max_chars`로 자르고 `truncated: true`를 붙인다.
   2. 한도를 넘으면 뒤 Case부터 뺀다(최소 1건). 뺀 수는 `omitted`다.
   3. 한 건으로도 넘으면 문장 상한을 600→300→150, 목록 상한을 10→5→3으로 줄인다(단계 1~4).
   4. 그래도 넘으면 권고 조치의 `rationale`과 Ticket 제목을 뺀다(단계 5, 2026-11-27 더함).
   5. 그래도 넘으면 경위 우선 단계(단계 6, 2026-11-27 더함): 권고 조치를 통째로 빼고 `recommendations_total`만 남기며 그 Case에 `recommendations_omitted: true`를 붙인다. 문장·목록 상한은 단계 5와 같고(150자·3개), `case`, `artifact`(verdict·analysis_round·timeline·techniques·impact·cause·further_risk·evidence_ids), `tickets`(id·origin·created_at), `alerts`는 남는다. 이유: L3가 Case를 참조하는 목적은 그 문제가 어떤 경위로 생겼는지 파악하는 것이고, 권고 조치는 그 목적에 가장 덜 필요하며 단계 4에서 1,128자로 가장 큰 덩어리였다.
   6. 그래도 넘으면 마지막 단계(단계 7, 2026-11-27 더함): Case마다 `{score, case: {id, incident_id, title, severity, confirmed_at, status}, artifact_total, recommendations_total, tickets_total, alerts_total, detail_omitted: true}`만 남긴다. 이 단계에서도 여러 Case가 안 들어가면 뒤 Case부터 빼고 `omitted`로 센다.
   7. 마지막 단계의 한 건도 안 들어갈 때만(설정 한도가 너무 작을 때) `ToolError("failed", reason="too_large")`다. 기본값에서는 나지 않는다.
   - `case.id`는 `status`가 `ok`인 모든 결과에 남는다. #393이 그 경로로 읽는다. `recommendations_omitted`가 true인 Case는 권고 조치 목록이 한도 때문에 빠졌고 개수만 `recommendations_total`에 있다(경위인 `artifact`는 있다).
7. **마이그레이션 `0312_agent_reader_case_search.sql`.** `soc_agent_reader`에 열 단위 SELECT만 준다.

   | 표 | 새로 줌 | 계속 막음 |
   |---|---|---|
   | `cases` | `title`, `summary`, `severity`, `entities`, `confirmed_at`, `status` | `confirmed_by`, `assignee`, `resolved_at`, `details` |
   | `tickets` | `title`, `origin` | `details`, `hunt_id`, `updated_at` |
   | `incident_artifacts` | `id`, `incident_id`, `analysis_round`, `verdict`, `timeline`, `techniques`, `impact`, `cause`, `further_risk`, `evidence_ids` | `summary`(= `cases.summary`), `assessed_severity`(= `cases.severity`), `created_at` |
   | `incident_proposals` | `artifact_id`, `kind`, `seq`, `priority`, `title`, `detail`, `rationale` | `id`, `created_at` |
   | `incident_reviews` | 없음 | 전부(D-082) |

   `incidents`·`alerts`는 이미 필요한 만큼 열려 있다(0007·0003). 쓰기 권한은 없다. 0003·0007 머리말의 "읽지 못한다"가 이 열들에 한해 바뀐다.
8. **설정 `config/default.toml`.**
   - `[tools.allowed]`의 `l3_hypothesize`와 `l3_verify` 둘 다에 `search_confirmed_cases`를 더한다(단계 키 `l3`는 만들지 않는다, D-086). 다른 태스크에는 넣지 않는다. 주석에 "가설 생성·검증 run이 모두 받는다"를 적는다.
   - `[tools.confirmed_cases]`(전부 초안값):

     | 키 | 값 | 뜻 |
     |---|---|---|
     | `limit_default` / `limit_max` | 2 / 3 | Case 하나의 결과가 무거워서 작게 잡는다 |
     | `min_score` | 0.5 | 짧은 질의와 긴 색인 텍스트 사이 점수는 짧은 제목끼리(#313의 0.6)보다 낮을 것으로 보고 재현율 쪽으로 잡았다. 실모델로 재지 못했다 |
     | `query_max_chars` | 200 | `search_similar_cases`와 같다 |
     | `text_max_chars` | 600 | 문장 칸마다 |
     | `list_max_items` | 10 | 목록마다 |
     | `result_max_chars` | 4000 | 도구 전용 결과 상한. `[agent.l3] max_tool_result_chars`(8,000)보다 낮게 둔다 |

   - `result_max_chars`가 따로 있는 이유: #392가 머지되면 #393의 호출 횟수 안내보다 먼저 도구가 L3 run에 보인다. 입력 예산(`max_input_chars` 48,000)은 모델 호출마다 앞 도구 결과까지 합쳐 재므로, 8,000자 결과가 몇 번 쌓이면 가설 생성 run 전체가 `budget_exceeded`로 끝나 Hunt가 저장되지 않는다.
9. **문서.**
   - `docs/decisions.md`: D-087와 기록 한 줄(이 계획 확정과 함께 넣는다).
   - `docs/security.md`(개발 단계에서): 「에이전트 도구의 한계」에 새 도구가 읽는 열과 계속 막는 열을 적고, 63행의 열 목록을 갱신한다. 결과 속 문장은 공격자가 넣은 문자열에서 나온 LLM 문장(2차 주입 경로)이라 `<tool_result>`로 감싸 데이터로만 다룬다고 적는다. 「모델 입력」에 지난 Incident의 분석 내용이 L3의 외부 LLM으로 새로 나간다는 것을 한 줄 더한다.
10. **테스트와 샘플.** 샘플은 `tests/fixtures/case_search/`에 손으로 만든다(Ticket·Alert·권고 조치가 있는 Incident, Artifact가 둘인 Incident, Artifact 없는 Case, `origin = l3` Ticket, 긴 필드 Case). IP는 문서용 대역, 도메인은 `example.com`을 쓴다.

## 바꿀 곳

- `src/soc/tools/confirmed_cases.py`(새 파일): 도구.
- `src/soc/tools/__init__.py`: `default_registry`에 도구를 더하고 docstring을 고친다. **#382와 겹칠 수 있음.**
- `src/soc/case_index/runtime.py`(새 파일): 서비스 구성과 설치.
- `src/soc/case_index/source.py`: 최신 Artifact 배치 SQL 상수.
- `src/soc/agent/executor.py`: `install_service` 호출 한 줄.
- `src/soc/db/migrations/0312_agent_reader_case_search.sql`: 열 단위 권한. **DB 권한 담당 확인 필요.**
- `config/default.toml`: `[tools.allowed]`의 `l3_hypothesize`·`l3_verify`, `[tools.confirmed_cases]`. **L3 담당 확인 필요.**
- `docs/decisions.md`: D-087, 기록 한 줄. `docs/security.md`: 위 9. **담당 확인 필요.**
- 기대값만 고치는 기존 테스트(지우거나 건너뛰지 않는다): `tests/test_agent_config.py`(l3 허용 목록, 새 설정 절), `tests/test_tools_registry.py`(도구 이름 목록), `tests/test_db_tables.py`(마이그레이션 목록), `tests/test_tools_similar_cases_db.py`(`SELECT origin FROM tickets`는 더 이상 거부가 아니다. 거부 목록에서 그 문장만 뺀다. 다른 거부 문장은 그대로다).
- 새 테스트와 `tests/fixtures/case_search/`.

## 다른 코드와 맞물리는 곳

- **읽기 역할 `soc_agent_reader`의 열 권한(0312).** 다른 담당의 DB 권한 결정(D-053·D-082)과 이어진다. `confirmed_by`·`assignee`·`incident_reviews`는 계속 막는다.
- **`[tools.allowed]`의 L3 태스크 키와 입력 예산.** L3 가설 생성·검증 run 둘 다 도구를 받는다(`l3_hypothesize`·`l3_verify` 둘 다에 둔다, D-086).
- **L2 함수 의존.** `get_service`(`soc.l2.branch.runtime`)의 모양이 바뀌면 이 도구도 영향을 받는다(#391과 같다). L2 파일은 고치지 않는다.
- **`soc.case_index.source`.** #391이 만든 모듈이다. 상수 하나를 더한다. 같은 사람(Interludeal)의 코드다.
- **#382와의 겹침.** `[tools.allowed]`, `tools/__init__.py`, 도구 이름 기대값 테스트, `docs/decisions.md`가 겹친다. `get_event`·`query_records`를 #382가 지우면 지난 Artifact의 `evt_` ID는 따라갈 수 없어지고, 이 도구가 보장하는 경로는 `get_alert`뿐이다(알럿 정규화는 #382도 그대로 둔다). #382 계획 댓글은 결정 번호 D-081을 쓴다고 적었지만 main의 D-081은 #384가 이미 썼다.
- **다음 이슈(#393)와의 약속.**
  1. 도구 이름은 `search_confirmed_cases`다.
  2. Agent Log tool 줄 `output`에서 `status == "ok"`이면 `results[].case.id`가 인용 가능한 Case ID다. `case.id`는 `status`가 `ok`인 모든 결과에 남는다. 한도 때문에 뺀 Case는 `results`에 없고 `omitted`로 센다. `detail_omitted`가 true인 Case는 상세 없이 ID·제목만 있다(개수는 `artifact_total`·`recommendations_total`·`tickets_total`·`alerts_total`). `recommendations_omitted`가 true인 Case는 권고 조치 목록이 한도 때문에 빠지고 개수(`recommendations_total`)만 있으며 `artifact`(경위)는 있다. 줄이기의 어느 단계에서도 `case.id`는 지우지 않는다.
  3. 컬렉션이 없으면 `{"status": "no_data", "reason": "no_index"}`다(Case ID 없음). Qdrant 장애는 Agent Log에 오류 줄(`unavailable`)로 남고 `output`에 결과가 없다.
  4. `aggregate`라 이 호출의 `call_id`만 장부에 들어간다. 결과의 Alert·Event ID는 다음 호출에 쓸 데이터다.
  5. 결과 모양은 `contracts/`에 두지 않는다. 대신 `results[].case.id` 경로를 고정하는 테스트가 있다.
- **담당 확인(PR 리뷰에서 받는다).** 이름은 계획 파일의 `owner:`로 추정한 것이다.
  - DB 읽기 권한(0312), `docs/decisions.md`·`docs/security.md`의 읽기 역할 결정, L3 허용 목록과 입력 예산: Pandyo(#313·#375·#389 담당).
  - `get_service` 의존, #382와의 겹침: Juhyeok0603(#370·#382 담당).
  - `src/soc/l3/`, `src/soc/pipeline/`, `contracts/`, `src/soc/similar/`는 바꾸지 않는다. `executor.py`는 에이전트 코어다.

## 범위 밖

- 색인(#391), L3 프롬프트와 `case_ids` 처리(#393), L1·L2 허용.
- 활성화 파이프(D-054)에 L3를 붙이는 일과 그때 필요한 서비스 설치 호출, L3 뉴스 선택.
- `pipeline/check.py` 수정.
- 분류·유사 사례·Case 임베더 인스턴스를 하나로 합치는 일.
- `contracts/`에 도구 결과 모양 두기.
- Event ID를 결과에 따로 주는 일(원본 목록은 Ticket·Alert뿐이다).

## 완료 기준

- [ ] 가짜 임베더·가짜 저장소로 검색하면 Case와 Artifact·권고 조치·원본 Ticket·Alert가 함께 나온다
- [ ] 결과의 Alert ID로 `get_alert`를 부를 수 있다(같은 L3 run 안에서). 부르면 근거 장부에 `alt_`가 들어가고, 이 도구만 부르면 `agl_`만 들어간다
- [ ] Qdrant hit의 Case가 DB에 없으면 결과에서 빠진다
- [ ] `soc_agent_reader`가 새로 허용한 열만 읽고 `confirmed_by`·`assignee`·`incident_reviews`·`SELECT *`·쓰기는 거부된다(DB 테스트)
- [ ] 기본 설정에서 `l3_hypothesize`·`l3_verify`에만 등록되고 다른 태스크에는 없다. 태스크 키만 있는 기본 설정에서 서비스가 설치된다. 서비스가 없으면(Qdrant 환경변수 없음 등) L3에서도 모델에게 보이지 않는다
- [ ] 결과에 반려 사유가 없다
- [ ] 결과가 `result_max_chars`를 넘으면 정한 순서로 줄고 `case.id`·`omitted`·`*_total`·`truncated`·`recommendations_omitted`·`detail_omitted` 표시가 남는다. 극단 샘플(Case 5)이 1위여도 기본값에서 `too_large`가 아니다. `too_large`는 설정 한도가 마지막 단계 한 건보다 작을 때만 난다
- [ ] Artifact 없는 Case는 `artifact: null`이고, `origin = l3` Ticket은 Alert 없이 Ticket 줄만 나온다
- [ ] 컬렉션 없음은 `no_data`/`no_index`, Qdrant·임베더 장애는 고정 문구 오류다
- [ ] `results[].case.id` 경로를 고정하는 테스트가 있다(#393 약속)
- [ ] 개발 중 손으로 만든 샘플의 실제 결과 길이를 재서 이 계획의 "바뀐 점"에 숫자로 적는다
- [ ] 기대값만 고친 기존 테스트를 개발 기록에 적는다
- [ ] 새 환경변수는 없다(`.env.example` 변경 없음). 새 설정 절 `[tools.confirmed_cases]`는 `default.toml`에 있다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과. 대상 DB·Qdrant 테스트는 `uv run pytest -m "db or qdrant"`로 확인한다
- [ ] `docs/decisions.md`에 D-087와 기록 한 줄, `docs/security.md` 갱신, `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

**테스트 구성**

| 마커 | 파일 | 대상 |
|---|---|---|
| 없음(기본) | `tests/test_tools_case_search.py`(새로) | 인메모리 Qdrant + 값을 정해 둔 가짜 임베더 + 가짜 `read_many`로 결과 모양·`case.id` 경로, 줄이기 순서와 `too_large`, DB에 없는 hit 버리기, `no_index`·`unavailable`, 잘못된 인자가 임베더·DB에 닿지 않음, l1·l2 미등록·l3만 등록, 서비스 없으면 미등록, 설정 오류, 닫는 태그 이스케이프, `get_alert` 뒤 장부 |
| 없음(기본) | 기존 테스트 4개 | 기대값만 수정 |
| `db` | `tests/test_tools_case_search_db.py`(새로) | 실제 표로 5문장 SQL(최신 Artifact 선택, 권고 조치 순서, Ticket·Alert 모으기, `origin = l3`), 읽기 역할이 허용 열만 읽고 막은 열·`incident_reviews`·`SELECT *`·쓰기는 거부 |
| `qdrant`(+`db`) | `tests/test_tools_case_search_qdrant.py`(새로) | 실제 Qdrant에서 승인→색인→검색, 없는 컬렉션이 `no_index`로 해석됨 |
| `embedder` | `tests/test_store_embedder.py` 보강 | 여러 스레드의 동시 `embed`가 같은 벡터를 낸다(이 PC에서 못 돌릴 수 있다) |

## 토론으로 정한 것

이슈 본문의 "정한 것"(L3 전용, `l3`에만 허용, 결과 구성, 반려 이력 제외, PostgreSQL 재검증, Qdrant·임베더가 없으면 등록하지 않음)은 그대로다. 아래는 이슈의 "정하지 못함"과 그사이 생긴 것을 정한 것이다.

1. **이름과 인자.** `search_confirmed_cases(query, limit)`. `min_score`는 인자로 열지 않고 설정으로만 둔다(모델이 임계값을 조절해도 얻는 것이 없다). 설정 절·번들 이름은 `confirmed_cases`(`search_similar_cases`↔`[tools.similar_cases]` 관례).
2. **기본값은 도구 전용 결과 상한을 둔다(사람이 정함: 추천 A 대신 B).** `[tools.confirmed_cases] result_max_chars = 4000`(초안). `limit_default` 2, `limit_max` 3, `text_max_chars` 600, `list_max_items` 10, `min_score` 0.5, `query_max_chars` 200은 모두 초안값이다. 이유: #392가 머지되면 #393의 호출 횟수 안내보다 먼저 도구가 L3 run에 보이고, L3 입력 예산(48,000자)을 넘으면 가설 생성 run 전체가 `budget_exceeded`로 끝나 Hunt가 저장되지 않는다. 줄이는 순서는 이 상한에 맞춘다. 개발 중 샘플의 실제 결과 길이를 재서 "바뀐 점"에 숫자로 적는다. `min_score`는 실모델로 재지 못해 초안값이다.
3. **결과 종류는 `aggregate`.** `records`로 주면 지난 Incident의 `alt_` ID가 이 run에서 본 적 없이 장부에 들어가 검증 run의 `confirmed` 근거 규칙(`l3/hunt/verify.py`의 `RECORD_PREFIXES`)이 약해진다. 결과의 Alert·Event ID는 다음 호출에 쓸 데이터로만 준다. #382의 `siem_refs`·근거 허용 목록은 이 도구의 결과 모양에 영향이 없다(이 도구는 계속 `aggregate`다).
4. **읽기 역할 열.** 위 방법 7의 표대로 연다. `confirmed_by`·`assignee`는 사람 계정 이름이고 헌팅에 쓸모가 없어 계속 막는다. `incident_artifacts.summary`·`assessed_severity`는 `cases`로 복사된 같은 값이라 열지 않는다(`ui_write.approve_incident`, `analyze/store.py`).
5. **임베더·서비스.** 워커와 같은 임베더·저장소 인스턴스를 쓴다. 서비스 구성은 `soc/case_index/runtime.py`, 설치는 `executor.py`의 `install_service` 옆 한 줄이다. 파이프는 바꾸지 않는다. 새 잠금은 두지 않고 `embedder` 마커 테스트로 확인한다.
6. **hit 재검증과 모으기.** `cases`에 행이 없는 hit만 뺀다. "대기 중인 Case를 뺀다"는 하지 않는다(읽기 역할이 `case_index_jobs`를 못 읽고 point가 있으면 색인된 것이다). SQL은 Case ID 배열로 조인하는 5문장이며, 최신 Artifact는 `source.py`에 배치 상수를 더해 고른다. Artifact 없는 Case는 `artifact: null`이다.
7. **원본 목록.** `tickets[] = {id, origin, title, created_at}`, `alerts[] = {id, title, time}`. `origin = l3` Ticket은 Alert 없이 Ticket 줄만 나오고 제목은 Hunt 가설 문장이다.
8. **`contracts/`에 두지 않는다.** 기존 도구 결과도 모두 `contracts/` 밖이다. `results[].case.id` 경로를 테스트로 고정하고 위 약속에 적는다.
9. **`security.md`.** 새 도구가 읽는 열과 막은 열, 결과 속 문장이 공격자 문자열에서 나온 LLM 문장(2차 주입 경로)이라는 점, 지난 Incident 분석 내용이 L3 외부 LLM으로 새로 나간다는 점을 적는다. 모델 입력 가림(#279)은 도구 결과도 거치므로 그대로 적용된다.
10. **컬렉션 없음·Qdrant 장애.** D-053과 같다. `no_data`/`no_index`, 장애는 고정 문구 오류.
11. **결과 속 근거 ID 정리(사람이 확인함).** Artifact 맨 위 `evidence_ids`에서 `agl_`를 뺀 `alt_`·`evt_`만 담고, 타임라인·기법 줄마다 붙은 `evidence_ids`는 뺀다. 근거: 저장된 `incident_artifacts.evidence_ids`는 `analyze/store.py:52-54`에서 `findings_citations`(최상위·타임라인·엔티티)와 `analysis_citations`(최상위·기법)를 합쳐 중복을 뺀 목록이라(`l2/analyze/tasks.py:21-35`), 줄마다 붙은 ID를 빼도 잃는 근거가 없다. `agl_`는 읽기 역할이 `agent_logs`를 읽지 못해 어떤 도구로도 따라갈 수 없다. 이슈 본문의 "근거 ID"와 달라지는 점이다.
12. **결정 번호.** 새 결정은 D-087다. #382 계획 댓글이 D-081을 쓴다고 적었지만 main의 D-081은 #384가 이미 썼다. #382 쪽에서 번호를 다시 매겨야 한다(담당에게 알린다).
13. **마이그레이션 번호.** `0312`(rebase로 바뀜. 처음에는 0311이었으나 #382가 `0311_agent_reader_raw_records.sql`을 먼저 머지했다).

## 바뀐 점

- 2026-11-27 · 결과 길이 실측(사람이 시킨 기록). 손으로 만든 샘플 결과의 모델에게 가는 직렬화 길이(`call_id` 포함)다. 표와 쌍별 값은 `docs/notes/392-case-search-tool.md` "확인 방법"에 있다.
  - Case 1(보통) 2,643자, Case 2(Artifact 없음) 858자, Case 3(`origin = l3` 섞임) 1,688자. 모두 줄이기가 필요 없다.
  - 긴 Case(4): 상한 없음 6,672자, 줄이기 단계 0~4에서 6,672 · 6,672 · 5,904 · 5,649 · 4,640자. 극단 Case(5): 상한 없음 30,550자, 기본 상한 22,128자, 단계 0~4에서 22,128 · 16,938 · 12,440 · 6,994 · 4,762자.
  - 기본 한도 4000에서 Case 둘을 함께 받으면: Case 1+2(3,388자)와 2+3(2,433자)은 줄이기 없이 들어간다(단계 0). 합쳐서 4,000자를 넘는 쌍(1+3 4,218자, 1+4 9,202자, 2+4 7,417자)은 뒤 Case를 빼고 앞 Case만 돌려주고 `omitted`를 1로 한다. 긴 Case가 앞이면(4+1) 맨 끝 단계(4,640자)도 4,000자를 넘어 `too_large`다. 줄이기 단계로 Case 둘이 함께 들어가는 쌍은 샘플에 없다.
  - **4000은 너무 빡빡해 보인다.** 맨 끝 단계(문장 150자·목록 3개)가 150자까지 차는 문장 칸(Case 제목·요약, 타임라인 3줄, 영향·원인·추가 위험, 권고 조치 3개의 제목·내용·근거, Ticket 제목 등) 스무 개쯤 때문에 약 4,600자에서 멈춘다(ID는 약 380자, 8%뿐). 문장이 150자를 넘고 목록이 3개 이상인 Case는 기본 한도에서 모두 `too_large`다. 5,000이면 긴 Case(4)가 단계 4로 들어간다. 값은 바꾸지 않았다. 사람이 정한다(상한을 올리거나, 맨 끝 단계를 더 줄이거나, `too_large` 대신 Case·요약만 돌려주는 최소 단계를 둘지).
- 2026-11-27 · 사람이 정함: 4000자 한도는 그대로 두고 줄이기 단계를 둘 늘렸다(위 방법 6). 단계 5는 권고 조치의 `rationale`과 Ticket 제목을 빼고, 단계 6(마지막)은 Case마다 id·제목 등과 개수만 남기며 `detail_omitted: true`를 붙인다. `too_large`는 한도가 마지막 단계 한 건보다 작을 때만 난다. D-087 문구, 완료 기준, #393과의 약속("`case.id`는 `status`가 `ok`인 모든 결과에 남는다. `detail_omitted`가 true인 Case는 상세 없이 ID·제목만 있다")을 고쳤다. 개수 키는 기존 결과와 맞춰 `tickets_total`·`alerts_total`이고 `artifact_total`은 최신 Artifact가 있으면 1, 없으면 0이다.
  - 단계별 실측(모델에게 가는 직렬화 길이, `call_id` 포함, 단계 0~6): Case 1 `2,643 ×5 · 2,441 · 477`, Case 2 `858 ×5 · 830 · 487`, Case 3 `1,688 ×5 · 1,560 · 484`, 긴 Case(4) `6,672 · 6,672 · 5,904 · 5,649 · 4,640 · 3,989 · 515`, 극단 Case(5) `22,128 · 16,938 · 12,440 · 6,994 · 4,762 · 4,021 · 518`.
  - 기본 한도 4000: 긴 Case(4)가 혼자면 단계 5(3,989자)로 들어간다. **한도까지 11자 여유뿐이다.** 극단 Case(5)는 단계 5가 4,021자라 단계 6(518자)이다. 한도를 가르는 곳이 단계 5라서 단계 5와 6 사이가 크게 벌어진다(3,989 → 515).
  - 쌍(한도 4000): 4+1은 4만 단계 5(3,989자, `omitted` 1), 4+5와 4+5+1도 4만(`omitted` 1, 2), 5+1은 둘 다 단계 6(882자), 5+4도 둘 다 단계 6(920자), 1+4와 1+3은 앞 Case만 단계 0(2,643자, `omitted` 1), 1+2는 둘 다 단계 0(3,388자).
  - 한도별로 긴 Case(4)가 혼자 들어가는 단계: 5,000 → 4(4,640자), 4,600~4,000 → 5(3,989자), 3,500~600 → 6(515자), 400 이하 → `too_large`. Case 5는 5,000 → 4(4,762자), 4,600·4,500 → 5(4,021자), 4,000~600 → 6(518자), 400 이하 → `too_large`.
  - 마지막 단계는 한도 4000보다 충분히 작다(515~518자, 한 건). 둘이면 882~920자.
- 2026-11-27 · 사람이 정함: 단계 5와 마지막 단계 사이에 "경위 우선" 단계를 더했다(위 방법 6). 한도 4000은 그대로다. 단계 번호가 바뀌었다: 위 「바뀐 점」 항목들의 마지막 단계는 이제 단계 7이다. 새 단계 6은 단계 5(문장 150자·목록 3개, 권고 근거·Ticket 제목 없음)에서 권고 조치를 통째로 빼고 `recommendations_total`과 `recommendations_omitted: true`만 남긴다. `artifact`(verdict·analysis_round·timeline·techniques·impact·cause·further_risk·evidence_ids), `tickets`(id·origin·created_at), `alerts`, `case`는 남는다. D-087 문구, 도구 설명, #393과의 약속("`recommendations_omitted`가 true인 Case는 권고 조치 목록이 한도 때문에 빠지고 개수만 있다")을 고쳤다.
  - 단계별 실측(모델에게 가는 직렬화 길이, `call_id` 포함, 단계 0~7). Case 1: `2,643 ×5 · 2,441 · 2,021 · 477`. Case 2: `858 ×5 · 830 · 868 · 487`. Case 3: `1,688 ×5 · 1,560 · 1,439 · 484`. 긴 Case(4): `6,672 · 6,672 · 5,904 · 5,649 · 4,640 · 3,989 · 3,284 · 515`. 극단 Case(5): `22,128 · 16,938 · 12,440 · 6,994 · 4,762 · 4,021 · 3,316 · 518`. Case 2는 권고 조치가 없어 단계 6이 단계 5보다 38자 크다(키가 붙음).
  - **새 단계로 Case 4·5 모두 4000에 들어간다.** 기본 한도 4000에서 Case 5가 혼자 1위면 단계 6(3,316자)로 `artifact`가 남는다. Case 4는 단계 5(3,989자)에서 이미 들어가서 새 단계를 쓰지 않는다(한도 3,900~3,500에서 단계 6, 3,284자). Case 4는 한도까지 11자 여유뿐이라 조금만 커지면 단계 6이다.
  - 쌍(한도 4000): 5+1·5+4는 앞 Case 5만 단계 6(3,316자, `omitted` 1). 4+1·4+5는 앞 Case 4만 단계 5(3,989자, `omitted` 1). 1+4·1+3은 앞 Case만 단계 0(2,643자). 1+2는 둘 다 단계 0(3,388자). 둘 다 단계 7(Case·개수만)로 들어가는 것은 한도가 약 3,300 이하일 때다(4+5는 3,200~1,000에서 920자, 5+1은 3,300~900에서 882자).
  - 한도별로 한 건이 들어가는 단계: Case 4는 5,000 → 4, 4,600~4,000 → 5, 3,900~3,500 → 6, 3,200~600 → 7, 400 이하 → `too_large`. Case 5는 5,000 → 4, 4,600 → 5, 4,000~3,500 → 6, 3,200~600 → 7, 400 이하 → `too_large`.
- 2026-11-27 · rebase로 바뀐 것(main에 #382(d2b2c98)·#396(cca906f)이 머지돼 사람이 `origin/main` 위로 rebase하라고 정함). 개발 커밋 7개는 충돌을 한 번에 풀려고 하나로 합쳤다.
  - 마이그레이션 번호: `0311_agent_reader_case_search.sql` → `0312_agent_reader_case_search.sql`(main에 #382의 `0311_agent_reader_raw_records.sql`이 있다). `tests/test_db_tables.py`의 목록에 둘 다 있다.
  - 결정 번호: D-085 → **D-087**(#382가 D-085·D-086을 썼다). 이 브랜치의 D-085 참조(코드 주석·테스트·설정 주석·security.md·계획·기록)를 모두 고쳤다. #382의 D-085를 가리키는 줄은 그대로다. 결정 표는 D-086 다음에 D-087을 둔다.
  - 도구 허용(D-086): `[tools.allowed]`의 키가 태스크 이름이라 `search_confirmed_cases`를 `l3_hypothesize`와 `l3_verify` 둘 다에 넣었다(계획대로 가설 생성·검증 run이 모두 받는다). 단계 키 `l3`는 만들지 않았다.
  - 서비스 설치 조건(`soc.case_index.runtime.build_service`): "l3에 허용"이 아니라 runner가 목록을 고르는 규칙(태스크 키가 있으면 그것을, 없으면 단계 키)과 같게 `l3_hypothesize`·`l3_verify`(없으면 `l3`) 중 하나에 도구가 있으면 설치한다. 태스크 키만 있는 기본 설정에서 서비스가 설치되는 테스트(`tests/test_case_index_runtime.py`)를 더했다.
  - `tools/__init__.py`, `test_agent_config.py`, `test_tools_registry.py`, `docs/security.md`, `docs/decisions.md`는 main(#382: Web 도구 삭제, `get_raw`, `siem_refs`)을 그대로 두고 이 브랜치의 추가분만 얹었다.
  - #382와 맞는지 확인한 결과: 영향 없음(자세한 것은 개발 기록 "다음 사람이 알아야 할 것").
- 2026-11-28 · CI db job 실패(PR #404, run 45977991224)를 고쳤다. 46개 오류(통과 810), 원인은 둘이다. 위 실측 항목들의 값은 이 항목이 대신한다(지난 항목은 고치지 않는다).
  - 원인 1(39개): 샘플의 auto Ticket 대부분이 Alert 둘을 가져 `tickets_auto_scenario_l1_single_alert_check`(0104, `origin <> 'l3'`이면 `cardinality(alert_ids) = 1`)를 어겼다. 실제 모델은 Incident 하나에 Ticket 여러 개, auto·scenario·l1 Ticket 하나에 Alert 정확히 하나, l3 Ticket은 Alert 없음·`hunt_id` 있음이다. 샘플을 이 모양으로 고쳤다(Alert가 둘인 Ticket을 Alert 하나씩 Ticket으로 나눔. Ticket 20 → 36개, Incident 1은 3개, 4는 6개, 5는 24개). 0104의 부분 유일 인덱스와 0001·0002의 제약도 지킨다.
  - 원인 2(7개): `test_incident_recommendations_db.py`·`test_ticket_title_db.py`의 옛 DB가 "그 마이그레이션만 빼고 전부" 적용해, 0312(`incident_proposals.priority`·`tickets.title`에 열 권한)가 0202·0109보다 먼저 적용돼 "column does not exist"로 실패했다. 옛 DB를 "그 번호 앞의 마이그레이션만"으로 바꿨다(`<`). 뒤 번호는 그 마이그레이션과 함께 나중에 적용된다. 0312는 고치지 않았다. 같은 방식의 `test_case_index_db.py`·`test_ticketing_policy_migration_db.py`·`test_ticketing_db.py`는 CI에서 통과했으므로 건드리지 않았다.
  - DB 없이 같은 실수를 잡는 기본 테스트 `tests/test_case_search_sample_constraints.py`를 더했다. 마이그레이션 파일을 읽어(값 목록은 SQL에서 읽는다) 샘플 여덟 표(raw_records·alerts·hunts·tickets·incidents·incident_artifacts·incident_proposals·cases)의 CHECK·UNIQUE·PK·FK를 본다. 옛 샘플에서는 16개를 잡는다(모두 Ticket의 Alert 개수).
  - 실측을 다시 쟀다(모델에게 가는 직렬화 길이, `call_id` 포함, 레포 밖 임시 스크립트. 옛 샘플로 옛 값을 먼저 재현해 확인했다). 단계 0~7. Case 1: `2,810 ×5 · 2,549 · 2,129 · 477`. Case 2·3은 그대로다. 긴 Case(4): 상한 없음 7,236, `7,236 · 7,236 · 6,468 · 6,045 · 4,660 · 4,009 · 3,304 · 515`. 극단 Case(5): 상한 없음 32,809, `22,127 · 16,937 · 12,439 · 6,994 · 4,762 · 4,021 · 3,316 · 518`.
  - **기본 한도 4000에서 긴 Case(4)가 들어가는 단계가 5에서 6으로 바뀌었다.** 단계 5가 3,989 → 4,009자로 4000을 넘는다(Ticket이 3개에서 6개가 돼 `tickets_total`이 붙었고 Ticket·Alert 목록 상한 밖이 늘었다). 단계 6은 권고 조치를 개수만 남기므로 Case 4는 4000에서 `recommendations_omitted`다. 4,100~4,600이면 단계 5다. 극단 Case(5)는 그대로 단계 6(3,316자). **값은 바꾸지 않았다.** 한도 4000이 빡빡하다는 지난 판단(단계 5의 11자 여유)이 실제로 나타난 것이다. 사람이 정한다.
  - 쌍(한도 4000): 4+1·4+5·4+5+1은 앞 Case 4만 단계 6(3,304자, `omitted` 1·1·2). 5+1·5+4·5+4+1은 앞 Case 5만 단계 6(3,316자). 1+4·1+3은 앞 Case만 단계 0(2,810자). 1+2는 둘 다 단계 0(3,555자), 2+3은 2,433자. 둘 다 단계 7(Case·개수만): 한도 3,300 이하(4+5는 3,300~1,000에서 920자, 5+1은 3,300~900에서 882자).
  - 바뀐 테스트 기대값(약하게 바꾸지 않았다): Case 1의 Ticket 2 → 3, Case 5의 `tickets_total` 12 → 24(목록 상한 5·4를 넘기는 Incident라는 의도는 그대로다), Case 4의 단계 2 한도 6,000 → 6,500(6,000이면 이제 단계 4), 단계 5를 보는 두 테스트의 한도 4000 → 4,500, 경위 우선 테스트에 Case 4·한도 4000을 더했다. D-087 문구의 "4,640자"는 "4,660자"로 고쳤다.
