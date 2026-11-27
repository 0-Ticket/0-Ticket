---
issue: 392
date: 2026-11-27
owner: Interludeal
plan: 392-case-search-tool.md
supersedes: []
---

# L3가 확정 Case와 Incident 경위를 검색하는 도구를 만들었다 (결과가 한도에 안 들어가면 단계로 줄이고 마지막엔 Case·개수만 남긴다)

## 한 일

- L3 가설 생성·검증 run이 `search_confirmed_cases(query, limit)`로 `confirmed_cases` 컬렉션(#391)을 문장 유사도로 검색한다. hit는 `case_id_of`로 Case ID로 되돌려 PostgreSQL에서 다시 확인하고 `cases`에 없으면 뺀다. 결과는 `aggregate`이며 Case(id·incident_id·제목·요약·심각도·엔티티·확정 시각·상태), 승인 당시(그 Incident의 최신) Artifact, 권고 조치, 원본 Ticket·Alert를 담는다. 반려 이력은 어디에도 없다.
- 허용은 `[tools.allowed]`의 `l3_hypothesize`와 `l3_verify`뿐이다(D-086, 단계 키 `l3`는 만들지 않았다). 서비스(임베더·`confirmed_cases` 저장소)는 `soc.case_index.runtime.install_service`가 `python -m soc.agent`가 시작할 때 설치한다. 두 태스크 중 하나에(태스크 키가 없으면 단계 키 `l3`로) 도구가 허용돼 있을 때만 만든다(runner가 목록을 고르는 규칙과 같다). #391의 색인 워커와 같은 인스턴스를 쓴다(`index.get_embedder`·`get_store`). Qdrant 환경변수나 임베더가 없으면 서비스가 없고 도구는 모델에게 보이지 않는다.
- 읽기는 `read_many` 한 번(한 연결)에 다섯 문장이다: Case(+전체 Ticket·Alert 개수), 최신 Artifact(`source.LATEST_ARTIFACTS_SQL`, #391의 단건 `LATEST_ARTIFACT_SQL`의 배치 형제), 그 Artifact의 권고 조치, Ticket·Alert(Case마다 `LATERAL … LIMIT`).
- 마이그레이션 0312이 `soc_agent_reader`에 열 단위 SELECT를 준다(`cases`·`tickets`·`incident_artifacts`·`incident_proposals`). `confirmed_by`·`assignee`·`incident_reviews`·`case_index_jobs` 등은 계속 막는다.
- 결과는 `[tools.confirmed_cases] result_max_chars`(4000, 초안)와 공용 한도 중 작은 쪽에 맞춘다. 줄이는 순서: 기본 상한(문장 600자·목록 10개) → 뒤 Case부터 뺀다(최소 1건, `omitted`) → 한 건으로도 넘으면 문장 600→300→150, 목록 10→5→3(단계 1~4) → 권고 조치 `rationale`과 Ticket 제목을 뺀다(단계 5) → **경위 우선(단계 6)**: 권고 조치를 통째로 빼고 `recommendations_total`만 남기며 `recommendations_omitted: true`를 붙인다(`case`·`artifact`·`tickets`(id·origin·created_at)·`alerts`는 단계 5의 상한 그대로 남는다) → 마지막(단계 7)은 Case마다 id·incident_id·제목·심각도·확정 시각·상태와 개수(`artifact_total`·`recommendations_total`·`tickets_total`·`alerts_total`)만 남기고 `detail_omitted: true`를 붙인다(여러 Case가 안 들어가면 뒤 Case부터 뺀다). `too_large`는 한도가 마지막 단계 한 건보다 작을 때만 난다. `status`가 `ok`인 모든 결과에 `case.id`가 남는다. 자르거나 뺀 것이 있으면 `truncated`와 `*_total`이 붙는다. 단계 5~7은 처음 구현(기본 한도에서 긴 Case가 `too_large`였다)을 실측으로 본 사람이 더하라고 정했다. 단계 6은 L3가 Case를 참조하는 목적(그 문제가 어떤 경위로 생겼는지)에 권고 조치가 가장 덜 필요하고(단계 4에서 1,128자로 가장 큰 덩어리) 단계 7로 떨어지면 경위가 통째로 빠지기 때문이다.
- `docs/security.md`를 고쳤다(새 열 목록, 2차 주입 경로, 지난 Incident 분석 내용이 L3 외부 LLM으로 나가는 점). 결정은 D-087다.

## 계획과 달라진 점

- **`truncated`와 `*_total`은 잘린 곳에만 붙는다.** 계획의 결과 모양 예시는 `evidence_total`·`alert_total`을 항상 두었다. 결과 한도가 빡빡해서 안 잘렸으면 키를 두지 않는다(키가 없으면 목록이 온전하다). 이름은 `alerts_total`·`tickets_total`·`recommendations_total`(결과 한 건 아래), `timeline_total`·`techniques_total`·`evidence_total`(`artifact` 아래), `entities_total`(`case` 아래)이다.
- **`truncated`는 결과 한 건(`results[i]`)에 붙는다.** 문장을 자르거나 목록을 줄인 Case에만 `true`다.
- **서비스 구성은 `src/soc/case_index/runtime.py`에 두었다.** 계획대로다. `ConfirmedCasesService`는 `soc.tools.confirmed_cases`를 import하고 반대는 없다(순환 없음).
- **목록 상한은 SQL에서 자른다.** Ticket·Alert가 수백 건인 Incident도 한 문장에서 `list_max_items`건만 읽는다. 전체 개수는 `cases` 문장(`ticket_total`·`alert_total`)에서 센다.
- **`tests/fixtures/case_search/cases.json`은 생성기로 한 번 만들어 커밋했다**(손으로 설계한 값, 긴 문장 칸을 반복 문장으로 채움). Case 5개: ①Artifact 2개·권고 조치·티켓 둘·알럿 셋, ②Artifact 없음, ③`origin = l3` Ticket 섞임, ④긴 Case, ⑤극단 Case.
- **기대값만 고친 기존 테스트는 계획의 4개 그대로다**(`test_agent_config.py`, `test_tools_registry.py`, `test_db_tables.py`, `test_tools_similar_cases_db.py`). 계획 목록 밖에서 고친 기존 파일은 없다. `tests/test_store_embedder.py`는 계획의 테스트 구성 표에 있던 보강(새 테스트 하나)이다.

## 다음 사람이 알아야 할 것

- **4000자에서 어느 단계에 걸리는지.** 긴 Case(4)는 단계 5가 3,989자라 한도까지 11자뿐이다. 조금만 더 크면 단계 6(경위 우선, 3,284자)으로 내려가 권고 조치가 개수만 남고, 극단 Case(5)는 단계 5가 4,021자라 이미 단계 6(3,316자)이다. 단계 6과 7 사이가 크게 벌어져(3,284 → 515) 단계 6도 넘는 Case는 id·제목·개수만 남는다. 그 Case의 경위는 L3가 `get_alert`로 원본을 따라가야 한다. 권고 조치가 빠진 Case(`recommendations_omitted`)에서 권고를 보려면 한도를 올리는 수밖에 없다(재검색으로는 같은 결과다). 상한을 5,000 안팎으로 올리면 긴 Case가 단계 4에서 들어간다. 값은 사람이 정한다(바꾸지 않았다). `recommendations_omitted`·`detail_omitted`는 모델이 알 수 있게 도구 설명에 적었다.
- **`artifact_total`은 최신 Artifact가 있으면 1, 없으면 0이다.** 결과는 최신 Artifact 하나만 다루므로 개수가 아니라 있고 없음이다. 개수 키 이름은 기존 결과와 맞춰 `tickets_total`·`alerts_total`이다(계획 지시문의 `ticket_total`·`alert_total`이 아니다).
- **가설 생성·검증 run이 모두 이 도구를 받는다.**(`l3_hypothesize`·`l3_verify` 둘 다에 넣었다.)
- **#393이 쓸 것.** 도구 이름은 `search_confirmed_cases`다. Agent Log tool 줄 `output`에서 `status == "ok"`이면 `results[].case.id`가 인용 가능한 Case ID다. `case.id`는 `status`가 `ok`인 모든 결과에, 줄이기의 어느 단계에서도 남는다(`tests/test_tools_case_search.py::test_results_follow_the_score_and_the_case_id_path_is_results_case_id`). 결과 한 건의 모양: `{score, case, artifact | null, recommendations, tickets, alerts}`. 한도 때문에 줄었을 때 읽는 법: `detail_omitted: true`인 Case는 상세 없이 `case`(id·incident_id·제목·심각도·확정 시각·상태)와 개수(`artifact_total`·`recommendations_total`·`tickets_total`·`alerts_total`)만 있다. `recommendations_omitted: true`인 Case는 권고 조치 목록이 빠지고 개수(`recommendations_total`)만 있으며 경위인 `artifact`·`tickets`·`alerts`는 있다. `truncated: true`와 `*_total`은 문장이나 목록을 자른 곳이다. 한도 때문에 못 보인 Case 수는 결과의 `omitted`다. 컬렉션이 없으면 `{"status": "no_data", "reason": "no_index"}`(Case ID 없음), Qdrant 장애는 오류 줄이다. 결과의 Alert·Event ID는 근거가 아니다. `aggregate`라 장부에는 이 호출의 `call_id`만 들어가고, L3가 `get_alert`를 다시 불러야 그 `alt_`가 장부에 올라간다(테스트가 확인).
- **`min_score` 0.5 등 모든 기본값이 초안이다.** 실모델로 재지 못했다. 이 PC에는 bge-m3 토크나이저·모델 파일이 없고 내려받지 않았다.
- **임베더 동시 사용.** 색인 워커(l2 단계 스레드)와 이 도구(l3의 도구 호출 전용 스레드)가 같은 `BgeM3Embedder`를 동시에 쓴다. 코드상 `embed`는 `_session.run`·`_tokenizer.encode`만 부르고 공유 상태를 바꾸지 않는다(절단 설정은 `_load_once`에서 한 번). 가짜 임베더로 겹침이 있어도 이 도구가 정상이고 같은 벡터가 나오는 것은 기본 테스트로 확인했다(`test_the_indexer_thread_and_the_tool_thread_can_use_one_embedder_together`). **실제 ONNX 세션·토크나이저의 동시 호출은 확인하지 못했다.** `embedder` 마커 테스트(`test_real_embedder_gives_the_same_vectors_when_threads_embed_together`)를 만들어 두었지만 모델 파일이 없어 돌리지 않았다. 실패하면 `embed`에 잠금을 둔다.
- **파이프(`soc.pipeline`)는 이 서비스를 설치하지 않는다.** 파이프는 L3를 항상 끈다(D-054). L3를 파이프에 붙이는 이슈가 `install_case_service(config)`를 더해야 한다.
- **`config/local.toml`에서 `[tools.allowed].l3`를 따로 정의했으면** `search_confirmed_cases`를 직접 더해야 한다. `[tools.confirmed_cases]`를 따로 정의했으면 `result_max_chars`를 포함한 일곱 키가 모두 있어야 한다(없으면 L3 run이 시작 전에 도구 설정 오류로 끝난다).
- **rebase로 바뀐 것(#382·#396 머지 뒤).** 마이그레이션은 0312(main의 0311은 #382의 `raw_records` 열 권한), 결정은 D-087(#382가 D-085·D-086)이다. 이 브랜치의 개발 커밋 7개는 충돌을 한 번에 풀려고 하나로 합쳤다. #382의 변경과 이 도구가 맞는지 코드로 확인했다: `get_alert`는 그대로(`records`, `id_fields=("details.id",)`)라 결과의 Alert ID를 다시 읽으면 장부에 오른다. `get_event`는 이제 class 0 원문 Event도 읽고(옛 정규화 행도 그대로 남아 있다) 지난 Artifact의 `evt_` ID를 따라갈 수 있다. `get_raw`는 `alt_`·`evt_`로도 원문을 읽는다. 근거 장부의 `siem_refs`(`ToolSession.siem_refs`, `CallContext.siem_docs`)는 SIEM 조회 도구만 채우므로 이 도구의 `aggregate` 결과(장부에는 `call_id`만)에 영향이 없다. `l3_verify`의 `confirmed` 근거 규칙(`verify.py`의 `RECORD_PREFIXES`, `alt_`·`evt_`)은 그대로이고, 이 도구의 결과 ID는 `get_alert`·`get_event`로 다시 읽어야 장부에 오른다. 아래 줄은 #382가 머지되기 전의 우려였다: `[tools.allowed]`·`tools/__init__.py`·`docs/decisions.md`·도구 이름 기대값 테스트가 겹쳤던 것은 이번 rebase에서 풀었다.
- **Windows에서 테스트를 돌릴 때** `PYTHONUTF8=1`이 필요하다(기존 문제).
- **확인하지 못한 것(이 PC에서).**
  - `uv run pytest -m db`와 `-m qdrant`를 돌리지 못했다. Docker Desktop이 디스크 입출력 오류(`input/output error`)로 컨테이너를 만들지 못했다. 같은 때 이 PC의 C: 볼륨 여유가 약 4MB였다(마무리 때 확인). 새 DB 테스트(`tests/test_tools_case_search_db.py`)와 Qdrant 테스트(`tests/test_tools_case_search_qdrant.py`)는 한 번도 실행되지 않았고, #391의 `tests/test_case_index_qdrant.py`도 아직 실제 Qdrant로 돌지 않았다.
  - **마이그레이션 0312과 다섯 SQL은 CI에서 처음 실행된다.** 눈으로는 열·표 이름, 읽기 역할이 받은 열만 쓰는지(WHERE·ORDER BY·JOIN 포함), 배열 파라미터 모양, `DISTINCT ON … ORDER BY incident_id, analysis_round DESC`를 다시 점검했다.
  - 마무리 점검에서 DB 테스트 삽입 도우미의 버그를 하나 고쳤다. `verdict`를 jsonb로 바꾸는 목록에 넣어 둬서 `incident_artifacts.verdict`(text)에 jsonb가 들어가 모든 DB 테스트가 fixture에서 실패할 뻔했다(`tests/test_tools_case_search_db.py`). 실행해서 확인한 것이 아니라 눈으로 찾아 고친 것이다.
  - 임베더 동시 호출의 실모델 확인(`-m embedder`)을 하지 못했다. 모델·토크나이저 파일이 없고 내려받지 않았다.
  - 기본값(`min_score` 0.5, 개수 2·3, 글자 수 600·목록 10, `result_max_chars` 4000)은 모두 초안이다. 실모델 점수와 실제 L2 출력 길이로 재지 못했다.
- **Docker 정리가 필요하다.** 사람이 Docker를 복구한 뒤 지운다: 컨테이너 `soc392-pg`(죽었는데 지워지지 않음), 네트워크 `zero-ticket-soc_default`, 볼륨 `zero-ticket-soc_qdrant-data`(`docker compose up -d qdrant`가 만들다 만 것). 이 PC의 C: 볼륨 여유가 거의 없다.
- 담당 확인(읽기 역할 열 목록·L3 허용 목록·입력 예산, L2 `get_service` 의존)은 PR 리뷰에서 받는다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- 기본 전체 `uv run pytest`: 2836개 통과(실제 임베더·DB·Qdrant 마커는 제외). 새 기본 테스트는 `tests/test_tools_case_search.py`, `tests/test_case_index_runtime.py`다. 기대값만 고친 기존 테스트(`test_agent_config.py`, `test_tools_registry.py`, `test_db_tables.py`)도 통과한다.
- **`-m db`·`-m qdrant`는 이 PC에서 돌리지 못했다**(사람이 Docker를 복구하지 않고 이대로 마무리하기로 했다). Docker Desktop이 디스크 입출력 오류(`input/output error`, containerd `meta.db`와 overlay2)로 컨테이너를 만들지 못했다(`docker compose up -d qdrant`와 `docker run postgres:16-alpine` 모두 같은 오류, 이미지를 내려받는 단계부터 실패). 새 DB 테스트 `tests/test_tools_case_search_db.py`(읽기 역할의 허용·거부 열, 실제 SQL이 샘플 행 기반 가짜와 같은 답을 내는지)와 `tests/test_tools_case_search_qdrant.py`(승인 → 색인 → 검색, 없는 컬렉션)는 **작성만 했고 실행하지 않았다.** 마이그레이션 0312과 다섯 SQL 문장은 눈으로만 확인했다. CI에서 처음 확인된다.
- 결과 길이 실측(샘플 결과의 모델에게 가는 직렬화 길이, `call_id` 포함, 레포 밖 임시 스크립트). 단계 0~4는 문장 600·300·150·150·150, 목록 10·10·10·5·3이고 단계 5는 단계 4에서 `rationale`·Ticket 제목을 뺀 것, 단계 6은 단계 5에서 권고 조치를 통째로 뺀 것(경위 우선), 단계 7은 Case·개수만이다.

  | Case | 상한 없음 | 단계 0 | 단계 1 | 단계 2 | 단계 3 | 단계 4 | 단계 5 | 단계 6 | 단계 7 |
  |---|---|---|---|---|---|---|---|---|---|
  | 1 (Artifact 2개, 보통) | 2,643 | 2,643 | 2,643 | 2,643 | 2,643 | 2,643 | 2,441 | 2,021 | 477 |
  | 2 (Artifact 없음) | 858 | 858 | 858 | 858 | 858 | 858 | 830 | 868 | 487 |
  | 3 (`origin = l3` 섞임) | 1,688 | 1,688 | 1,688 | 1,688 | 1,688 | 1,688 | 1,560 | 1,439 | 484 |
  | 4 (긴 Case) | 6,672 | 6,672 | 6,672 | 5,904 | 5,649 | 4,640 | 3,989 | 3,284 | 515 |
  | 5 (극단 Case) | 30,550 | 22,128 | 16,938 | 12,440 | 6,994 | 4,762 | 4,021 | 3,316 | 518 |

  Case 2는 권고 조치가 없어 단계 6이 단계 5보다 오히려 38자 크다(`recommendations_total`·`recommendations_omitted` 키가 붙는다). 어차피 단계 5에서 먼저 들어가므로 영향이 없다.

- 기본 한도 4000에서의 결과(앞 Case부터 순서대로, `fit_results`):
  - Case 4만: 단계 5(3,989자). 한도까지 11자 여유. Case 5만: 단계 6(3,316자, 경위 우선, `artifact` 남음).
  - 4+1: 앞 Case 4만 단계 5(`omitted` 1). 4+5와 4+5+1도 4만(`omitted` 1·2).
  - 5+1: 앞 Case 5만 단계 6(3,316자, `omitted` 1). 5+4와 5+4+1도 5만(`omitted` 1·2).
  - 1+4·1+3: 앞 Case만 단계 0(2,643자, `omitted` 1). 1+2: 둘 다 단계 0(3,388자). 2+3: 둘 다 단계 0(2,433자).
  - 즉 Case 둘이 함께 들어가는 것은 둘 다 단계 0일 때(1+2, 2+3)와, 한도가 단계 6의 한 건(약 3,300)보다 작아 둘 다 단계 7(Case·개수만)로 들어갈 때다(4+5는 한도 3,200~1,000에서 920자, 5+1은 3,300~900에서 882자). 900 아래에서는 앞 Case만 단계 7이다.
- 한도별로 한 건이 들어가는 단계: Case 4는 30,000 → 0, 6,000 → 2, 5,700 → 3, 5,000 → 4(4,640자), 4,600~4,000 → 5(3,989자), 3,900~3,500 → 6(3,284자), 3,200~600 → 7(515자), 400 이하 → `too_large`. Case 5는 5,000 → 4(4,762자), 4,600 → 5(4,021자), 4,000~3,500 → 6(3,316자), 3,200~600 → 7(518자), 400 이하 → `too_large`.
- 마지막 단계(7)는 4000보다 충분히 작다(한 건 477~518자, 둘이면 882~920자). `tests/test_tools_case_search.py`는 한도 1,500에서 한 건이 750 미만임을 확인한다. 경위 우선 단계(6)는 Case 4·5가 각각 한도 3,500·4000에서 `artifact`(타임라인 3줄·기법·영향·원인·추가 위험·근거 ID)를 남기고 권고 조치만 개수로 바뀌는 것을 확인한다.
- 줄이기 단계 4(문장 150자·목록 3개)의 구성(긴 Case 4, 본문 4,525자, `call_id`·머리 칸을 더하면 4,640자): `case` 630, `artifact` 1,564(타임라인 570·기법 204·영향/원인/추가 위험 각 153·근거 ID 132), 권고 조치 1,128(셋 × 약 376), Ticket 564, Alert 489, 그 밖 150. ID(Ticket·Alert·근거)는 합쳐 약 380자(8%)뿐이고 나머지는 150자까지 차는 문장 칸이다. 단계 5가 빼는 `rationale`·Ticket 제목은 약 650자(4,640 → 3,989), 단계 6이 빼는 권고 조치 나머지는 약 700자(3,989 → 3,284)다.
- 4000이 빡빡해 보이는지: 단계 5~7이 있어 오류는 나지 않고 Case 4·5 둘 다 `artifact`(경위)를 남긴 채 4000에 들어간다. 다만 Case 4의 단계 5는 여유가 11자뿐이다. **값은 바꾸지 않았다.**
