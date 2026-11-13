---
issue: 313
date: 2026-11-13
owner: Pandyo
plan: 313-similar-cases-tool.md
supersedes: []
---

# L1·L2 에이전트가 비슷한 과거 사례를 검색하고, L1 판정이 그 색인을 채우게 했다

## 한 일

L1·L2 에이전트가 `search_similar_cases`로 판정이 끝난 과거 Ticket 중 비슷한 사례를 찾는다(D-053). `ticket_id`(그 Ticket의 Alert 제목으로 찾고 자기 자신과 같은 Incident의 Ticket은 뺀다) 또는 `query`(짧은 문장) 중 하나를 주고, `limit`·`min_score`로 좁힌다. 결과마다 점수, 판정(`decision`·`confidence`·`reason`), 종결 상태, 시각, 대표 엔티티, `case_id`, `decided_by`가 있다.
- `decided_by`는 그 Ticket의 Incident에 Case가 있으면 `human`, 그 밖에는 `agent`다. 사람이 `dismissed`로 닫은 Incident도 Case가 없으면 `agent`다.
- 색인은 새 컬렉션 `ticket_verdicts`다. `L1Worker`가 Ticket 판정을 저장한 직후 같은 프로세스에서 임베딩해 point를 쓴다(point ID는 Ticket ID에서 `tkt_`를 뗀 UUID, payload는 비움). 실패하면 경고만 남기고 L1 판정은 그대로다. 이미 쌓인 Ticket은 `uv run python -m soc.similar reindex [--recreate]`로 채운다(출력: `processed`·`succeeded`·`skipped`·`failed` 건수).
- 상태·판정·시각·엔티티는 검색할 때 PostgreSQL에서 읽는다. 에이전트 읽기 역할에 열 단위 SELECT를 줬다(0007): `tickets`(id, status, verdict, entities, alert_ids, created_at), `incidents`(id, ticket_ids, status), `cases`(id, incident_id).
- 임베더와 저장소는 실행기(`python -m soc.agent`)가 시작할 때 한 번 만들어 `soc.tools.services`에 등록하고, `run_task`가 실행마다 도구 세션(`CallContext.services`)에 넘긴다. 도구를 허용하지 않았거나 Qdrant 환경변수가 없으면 만들지 않고, 도구는 모델에게 보이지 않는다(`ToolSpec.requires_service`).
- 프롬프트 `l1.md`, `l2.md`에 "과거 판정은 참고 증거이고 `decided_by=agent`는 틀렸을 수 있다"를 더했다. `l1.md`에는 "에이전트 판정 사례만으로 benign 확신도를 올리지 않는다"와 Alert 1차 판정에는 `query`를 쓰라는 문장도 있다.

## 계획과 달라진 점

- **읽기 권한에 `tickets.alert_ids`를 더했다.** 계획 "바뀐 점"(2026-11-13)에 적었다. `ticket_id` 검색이 Alert 제목을 읽어야 하는데 Ticket과 Alert의 연결이 이 열뿐이다.
- **임베딩 텍스트에서 Event 요약을 뺐다.** 계획의 "Alert 제목, Event 요약, Hunt 가설·이유"와 다르다. 기존 `read_branch_data`는 Event를 판정의 근거 ID로만 찾아서, 판정이 있는 색인 쪽에는 Event 요약이 있고 판정 전 Ticket의 질의 쪽에는 없다. 같은 종류의 텍스트로 비교하려고 Alert 제목만 쓰고, Alert가 없는 `origin=l3` Ticket은 색인할 때만 Hunt 가설을 쓴다(`soc.similar.text`). Hunt 이유는 LLM 문장이라 넣지 않았다.
- **`number` 인자 형식을 레지스트리에 더했다.** `min_score`가 0~1 소수라서다. `Arg.minimum`·`maximum`의 타입이 `int`에서 `float`로 넓어졌다. 기존 `integer` 검사는 그대로다(bool·float은 여전히 거부).
- **`ToolSpec`에 `requires_service`를 더했다.** 계획의 "`CallContext`·`ToolSession`에 선택 필드"를 `ToolSpec`까지 넓힌 것이다. 필요한 공유 객체가 없으면 그 도구는 설정 검사 없이 등록에서 빠진다. 기본값은 없음이라 기존 도구는 같다.
- **`ticket_id`가 없는 `origin=l3` Ticket은 `no_data`(`no_text`)다.** 에이전트 읽기 역할이 `hunts`를 읽지 못해서 Hunt 가설로 질의를 만들 수 없다.
- **Qdrant에서 결과의 두 배(+ 뺄 Ticket 수)를 받는다.** 뺄 Ticket과 PostgreSQL에 없는 point(파생 색인의 누락·잔재)를 버려도 `limit`이 차게 하려는 것이다. 상한은 200이다.
- **기존 테스트의 기대값을 고쳤다**(지우거나 건너뛰지 않음): `test_agent_config.py::test_default_tools_config`(허용 목록·`similar_cases` 표), `test_tools_registry.py::test_default_registry_has_the_five_tools`(도구 이름 목록), `test_db_tables.py`(마이그레이션 목록), `test_tools_db.py::test_reader_role_is_denied_elsewhere`(아래 "다음 사람이 알아야 할 것").
- **코드를 테스트보다 먼저 쓴 곳이 있다.** 레지스트리 `number`·`services`, `similar` 패키지(텍스트·색인·재색인·실행기 등록)는 구현 뒤에 테스트를 썼다. 도구 `similar_cases.py`와 임베더 잠금은 테스트를 먼저 쓰고 실패를 확인했다(임베더 잠금은 잠금을 빼면 실패하는 것도 확인).

## 다음 사람이 알아야 할 것

- **마이그레이션 뒤 재색인을 한 번 돌려야 이미 쌓인 Ticket이 검색된다.** `uv run python -m soc.similar reindex`. 그 전에는 도구가 `no_data`(`no_index`)를 돌려준다(오류가 아님). 새 Ticket은 L1이 판정하는 대로 색인된다.
- **`config/local.toml`에서 `[tools.allowed]`의 `l1`·`l2`를 따로 정의했으면 `search_similar_cases`를 직접 더해야 한다.** `QDRANT_URL`이 없으면 도구는 등록되지 않고 색인도 하지 않는다.
- **`python -m soc.agent`에 약 2.27GB 모델이 상주한다.** 도구를 허용했고 `QDRANT_URL`이 있을 때만 만들고, 모델은 처음 임베딩할 때 받아 올린다(첫 판정이 느릴 수 있다).
- **`decided_by=human`은 지금 실데이터에서 나오지 않을 수 있다.** Case를 만드는 코드(승인 API)가 `src/soc`에서 보이지 않았다(`grep "INSERT INTO cases"`). 테스트는 DB에 Case를 직접 넣어 확인했다.
- **D-025의 자동 종결은 구조적으로 막지 못한다.** L1이 `agent` 판정 사례를 보고 확신도 0.8 이상 benign을 내면 코드가 바로 `closed`로 닫는다. 프롬프트 경고만 있다(D-053 메모, `docs/security.md`).
- **`tickets`에 열 단위 권한을 주면 `SELECT count(*) FROM tickets`는 허용된다.** 기존 거부 테스트의 `count(*)` 문장을 `details` 열 조회로 바꿨다. 같은 의도(읽기 역할은 `tickets` 전부를 못 읽는다)를 더 정확히 본다.
- **색인은 Qdrant에만 있어 PostgreSQL 트랜잭션에 묶이지 않는다.** 색인에 실패한 Ticket은 검색되지 않고(경고 로그만), 재색인으로 채운다. 반대로 PostgreSQL에서 지워진 Ticket의 point는 남을 수 있는데 도구가 행이 없으면 버린다.
- **같은 Incident의 Ticket 제외는 `ticket_id` 검색에서만 된다.** 도구는 지금 판정 중인 Ticket을 모르므로 `query` 검색은 자기 자신이 색인돼 있으면 결과에 나올 수 있다. Alert 1차 판정은 Ticket이 없어 `query`만 쓴다.
- **`BgeM3Embedder._load()`에 잠금을 더했다.** 단계 스레드 여러 개가 첫 호출을 겹쳐도 모델을 한 번만 올린다. `_session`을 마지막에 써서, 잠금 밖의 빠른 확인이 나머지 값(`_tokenizer`·`_output`)이 준비된 뒤에만 참이 되게 했다.
- **한국어 질의 품질은 확인하지 못했다.** bge-m3는 다국어지만 색인 텍스트는 Alert 제목이라 SIEM 룰 언어에 달려 있다. 아래 측정은 영어 제목과 한국어 한 건뿐이다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 1851건 통과
- `uv run pytest -m "db or qdrant"`(로컬 PostgreSQL·Qdrant 컨테이너): 534건 통과
- 주요 테스트
  - `tests/test_tools_similar_cases.py`: 유사도 순서, `decided_by`·`case_id`, 자기 자신과 같은 Incident 제외, `min_score`·`limit`, 결과 없음, DB 행·판정이 없는 hit 버리기, 없는 컬렉션(`no_index`)과 저장소 장애(`unavailable`), 이유·엔티티 길이, 결과 한도 줄이기, 잘못된 인자(둘 다 없음·둘 다 있음·길이·`kind`)가 임베더·DB에 닿지 않음, 서비스가 없으면 미등록, `l3` 미허용, 설정 오류, 닫는 태그 이스케이프
  - `tests/test_tools_similar_cases_db.py`(`db`): 읽기 역할이 지정 열만 읽고 `details`·다른 열·쓰기는 거부, 실제 표에서 `human`/`agent`/`dismissed`, 같은 Incident 제외, 판정 전 Ticket 검색, `origin=l3` 검색 불가, Qdrant에만 있는 point 버리기
  - `tests/test_similar_db.py`(`db`): 색인 텍스트에 판정 이유 없음, 빈 payload point, 재색인(건수·`--recreate`·일부 실패), 색인 실패를 삼키는 함수
  - `tests/l1/test_l1_judge_db.py`(`db`): 판정 저장 뒤에 색인, Alert·실패한 run은 색인 안 함, 색인 오류가 판정·실패 횟수를 바꾸지 않음, 실행기가 등록한 서비스를 `build_worker`가 받음
  - `tests/test_similar_qdrant.py`(`qdrant`, 실제 Qdrant): 빈 payload 왕복과 코사인 순서, `min_score`, 컬렉션 없음 해석
  - `tests/test_store_embedder.py`: 여러 스레드가 겹쳐도 모델을 한 번만 올림(잠금을 빼면 실패 확인), `tests/test_tools_services.py`: `number` 인자·`requires_service`·`ctx.services`
  - `tests/test_agent_executor.py`: 실행기가 워커를 만들기 전에 서비스를 등록
- **`min_score` 기본값 0.6 (실모델 측정, 2026-11-13, 임시 스크립트, 커밋 안 함).** bge-m3(고정 revision)로 영어 Alert 제목 11개(한국어 1개 포함)의 55쌍 코사인을 쟀다. 같은 공격으로 본 문장 쌍은 0.61~0.92(표현이 비슷하면 0.85 이상, 표현이 다른 SSH·포트스캔 바꿔 쓴 쌍은 0.61~0.64)였고, 다른 공격 쌍은 중앙값 약 0.50, 최대 0.70(둘 다 "external host"가 들어간 SSH 무차별 대입과 포트 스캔)이었다. 0.6이면 바꿔 쓴 같은 공격을 놓치지 않고 대부분의 다른 공격이 빠지지만 겹치는 낱말이 많은 다른 공격은 섞일 수 있다. 도구가 점수를 같이 돌려주고 프롬프트가 "참고 증거"라고 하므로 재현율 쪽을 택했다. 표본이 작아 실제 SIEM 제목으로 다시 재고 `[tools.similar_cases] min_score`를 조정해야 한다.
- **실제 모델 경로 확인에서 알게 된 것(이 이슈 코드가 아님).** macOS에서 `BgeM3Embedder`는 기본 Hugging Face 캐시(심링크)로 `model.onnx`를 열 때 `External data path validation failed`로 실패한다(onnxruntime 1.31.1). #257 기록은 심링크가 없는 Windows에서 확인한 것이다. 측정은 파일을 복사한 폴더를 가리키게 `hf_hub_download`를 바꿔서 했다. `python -m soc.similar reindex`와 실행기의 첫 임베딩도 macOS에서는 같은 이유로 실패할 수 있다. 별도 이슈가 필요하다.
