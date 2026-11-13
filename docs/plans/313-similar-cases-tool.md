---
issue: 313
date: 2026-11-13
owner: Pandyo
supersedes: []
---

# 유사 사례 검색 도구 추가 (Ticket·Case)

## 목표

L1·L2 에이전트가 `search_similar_cases`로 판정이 끝난 과거 Ticket 중 비슷한 사례를 찾아, 그 판정과 종결 상태와 사람 확정 여부(`decided_by`)를 참고 증거로 쓰게 한다. 판정이 끝난 Ticket을 담는 새 컬렉션과 색인 코드까지 이 이슈에서 만든다. 지금 컬렉션(`ticket_branch`)에는 Incident에 붙은 `linked` Ticket만 있어 L1이 종결한 오탐을 참고할 수 없기 때문이다.

## 방법

데이터가 흐르는 순서: L1 판정 적용 → 같은 프로세스에서 임베딩해 `ticket_verdicts`에 색인 → 도구가 질의를 임베딩해 검색 → hit의 Ticket을 PostgreSQL에서 읽어 결과를 만든다. Qdrant는 파생 색인이고 권위 원본은 PostgreSQL이다(D-013).

**1. 색인 (`src/soc/similar/`, 새 패키지)**
- 용도 이름 `ticket_verdicts`의 컬렉션을 기존 `VectorStore`(`src/soc/store/qdrant.py`)로 쓴다. `store/`는 업무 개념을 넣지 않는 계층이라 바꾸지 않는다.
- 색인 대상: `verdict`가 있는 Ticket(`closed`, `escalated`, `linked`, `held` 중 판정이 있는 것). 판정 없이 실패해 `held`가 된 Ticket은 넣지 않는다. 모든 `origin`을 포함한다.
- point ID는 Ticket ID에서 `tkt_`를 뗀 UUID, payload는 비운다. 상태·판정·시각은 PostgreSQL에서 읽으므로 상태가 바뀌어도 다시 쓰지 않는다.
- 임베딩 텍스트: Alert 제목, Event 요약, Hunt 가설·이유(해당하면)를 줄바꿈으로 연결한다. `verdict.reason`은 넣지 않는다. 기존 `embedding_text`(`src/soc/l2/branch/embed.py`)는 바꾸지 않고, 같은 문맥 읽기(`read_branch_data`·`build_context`)를 재사용하는 이유 없는 변형을 새로 둔다. 읽기 함수가 `status` 기대값을 요구하면 계획 변경 없이 호출 쪽에서 맞춘다.
- 쓰는 시점: `L1Worker`(`src/soc/l1/judge.py`)가 판정을 PostgreSQL에 적용한 뒤 같은 프로세스에서 색인한다. 실패하면 경고만 남기고 L1 판정은 그대로 둔다(L2 `_index`와 같은 방식). Qdrant 쓰기는 PostgreSQL 트랜잭션에 묶지 않는다.
- 재색인 명령: `uv run python -m soc.similar reindex [--recreate]`. PostgreSQL에서 판정이 있는 Ticket을 읽어 채우고 처리·성공·실패 건수를 출력한다. 이미 쌓인 Ticket을 채우는 데도 쓴다.

**2. 도구 `search_similar_cases` (`src/soc/tools/similar_cases.py`)**
- 입력: `ticket_id` 또는 `query`(둘 중 하나), `limit`, `min_score`. `kind`는 두지 않는다(결과는 항상 Ticket 단위).
- `ticket_id` 검색: PostgreSQL에서 그 Ticket의 Alert·Event를 읽어 질의 텍스트를 만들고 임베딩한다(판정이 아직 없는 `new` Ticket도 가능). 결과에서 자기 자신과 같은 Incident에 속한 Ticket을 뺀다.
- `query` 검색: 짧은 텍스트(길이 상한)를 임베딩한다. 자기 제외는 하지 않는다(도구는 지금 판정 중인 Ticket을 모른다). L1의 Alert 1차 판정은 Ticket이 없어 `query`만 쓴다.
- 결과 각 건: `ticket_id`, `score`, `verdict.decision`과 이유 요약(길이 제한), `status`, `created_at`, 대표 엔티티(개수·길이 제한), `case_id`(Case가 있으면 ID, 없으면 null), `decided_by`. Qdrant hit의 Ticket이 PostgreSQL에 없거나 판정이 없으면 버린다.
- `decided_by`: 그 Ticket의 Incident(`incidents.ticket_ids`)에 Case(`cases.incident_id`)가 있으면 `human`, 그 밖에는 `agent`. 사람이 `dismissed`로 닫은 Incident는 `agent`로 둔다.
- 결과가 없으면 빈 목록과 이유 이름(예: `no_match`)을 돌려주고 예외로 죽지 않는다. 컬렉션이 없으면 `no_data`.
- 결과 종류는 `aggregate`이고 `ctx.fits`로 도구 결과 한도에 맞춘다. 밖에서 온 문자열(이유, 엔티티 값)은 레지스트리의 데이터 구분자와 D-048 입력 필터를 그대로 거친다.
- 설정 `[tools.similar_cases]`: `limit` 기본값·상한, `min_score` 기본값, `query` 최대 길이, 이유 요약 최대 길이, 엔티티 개수. `check_config`로 값 모양을 실행 시작 전에 검사한다. 허용 단계는 `[tools.allowed]`의 `l1`·`l2`.
- Qdrant 환경변수나 임베더를 만들 수 없으면 `configure`가 None을 돌려 도구를 등록하지 않는다(`lookup_indicator`와 같은 방식).

**3. 임베더·Qdrant 주입 (공용 코드)**
- 실행기(`python -m soc.agent`)가 시작할 때 임베더와 `ticket_verdicts` 저장소를 한 번 만들어 도구 세션에 넘긴다. 도구 핸들러는 `ctx`로만 받는다(D-049 유지). L1 색인도 같은 임베더를 쓴다.
- `CallContext`와 `ToolSession`(`src/soc/tools/registry.py`)에 선택 필드를 더한다. 기본값은 없음이라 기존 도구의 동작은 바뀌지 않는다.
- `BgeM3Embedder._load()`(`src/soc/store/embedder.py`)에 잠금을 더한다. 여러 단계 스레드가 첫 호출에서 모델을 두 번 올리지 않게 하는 변경이고 다른 동작은 바꾸지 않는다.
- `python -m soc.agent` 프로세스에 약 2.27GB 모델이 올라간다. 도구를 허용했고 Qdrant 환경변수가 있을 때만 만든다.

**4. 읽기 권한**
- 마이그레이션 `0007_agent_reader_tickets.sql`(공통 대역): `soc_agent_reader`에 열 단위 SELECT만 준다. `tickets`(id, status, verdict, entities, alert_ids, created_at), `incidents`(id, ticket_ids, status), `cases`(id, incident_id). `tickets.details`와 쓰기는 주지 않는다. 0003 헤더의 "권한을 주지 않는다"는 고치지 않고 D-053에 갱신 범위를 적는다.
- 도구는 열 이름을 직접 적어 읽는다(`SELECT *` 금지).

**5. 프롬프트·결정 목록·문서**
- `l1.md`, `l2.md`: 사용법 한 줄. "비슷한 사례의 판정은 참고 증거이고 정답이 아니다. `decided_by=agent`인 과거 판정은 틀렸을 수 있다." `l1.md`에는 "에이전트 판정 사례만으로 benign 확신도를 올리지 않는다"와 "`ticket_id`가 없으면 짧은 `query`를 쓴다"를 더한다.
- `docs/decisions.md`: D-053 추가, D-013 메모 보완, 기록 줄. 기존 충돌 표식과 D-049/D-050 중복은 고치지 않는다.
- `docs/security.md` "에이전트 도구의 한계": `tickets`·`incidents`·`cases`는 위 열만 읽는다는 한 줄.
- `.env.example`: 새 환경변수 없음(Qdrant 주소는 기존 `QDRANT_URL`).

## 바꿀 곳

- `src/soc/similar/`: 새 패키지(텍스트 생성, 색인 쓰기, 재색인 명령 `__main__`)
- `src/soc/tools/similar_cases.py`: 새 모듈. `src/soc/tools/__init__.py`: `default_registry()`에 추가, docstring 고침
- `src/soc/tools/registry.py`: `CallContext`·`ToolSession`에 선택 필드(기본 없음)
- `src/soc/store/embedder.py`: `_load()`에 잠금
- `src/soc/l1/judge.py`: 판정 적용 뒤 색인 호출
- 실행기 시작 코드(`src/soc/agent/`): 임베더·저장소를 만들어 도구 세션에 주입(구현 전에 위치를 다시 읽고 확인한다)
- `src/soc/db/migrations/0007_agent_reader_tickets.sql`: 새 파일
- `config/default.toml`: `[tools.similar_cases]` 추가, `[tools.allowed]`의 `l1`·`l2`에 도구 추가
- `src/soc/agent/prompts/l1.md`, `l2.md`: 위 문장
- 테스트: `tests/test_similar_*.py`(텍스트·색인·재색인, 가짜 임베더), `tests/test_tools_similar_cases.py`(순수 검증), `tests/test_tools_similar_cases_db.py`(`db`), `tests/test_similar_qdrant.py`(`qdrant`), 임베더 잠금 테스트, 기본 레지스트리·기본 설정·읽기 역할 권한 기대값을 확인하는 기존 테스트(`test_agent_config.py`, `test_tools_registry.py`, `test_db_tables.py`, `test_tools_db.py` 등)는 지우거나 건너뛰지 않고 기대값만 고친다
- `tests/fixtures/`: 손으로 만든 작은 Ticket·Alert·Event 샘플(문서용 IP 대역, `example.com`)
- `docs/decisions.md`, `docs/security.md`, `docs/notes/313-similar-cases-tool.md`(개발·마무리 단계에서)

## 다른 코드와 맞물리는 곳

- 테이블: 새 마이그레이션은 권한만 주고 테이블·열은 바꾸지 않는다. `soc_agent_reader`에 위 세 표의 지정 열 SELECT가 생긴다(D-053).
- Qdrant: 새 컬렉션 `ticket_verdicts`. `ticket_branch`와 L2 분류 코드는 바꾸지 않는다.
- 공용 코드: `CallContext`·`ToolSession`(선택 필드 추가), `BgeM3Embedder._load()`(잠금), `L1Worker`(판정 뒤 색인 호출, 실패해도 판정 유지). L1·L2 담당 확인은 끝났다(2026-11-13).
- 설정 키: `[tools.similar_cases]` 신설, `[tools.allowed]`의 `l1`·`l2`에 `search_similar_cases` 추가. `config/local.toml`에서 `l1`·`l2`를 따로 정의한 사람은 도구 이름을 직접 더해야 한다(기록에 적는다).
- 환경변수: 없음(기존 `QDRANT_URL`, `AGENT_DATABASE_URL`, `DATABASE_URL`).
- 실행 비용: `python -m soc.agent` 프로세스에 약 2.27GB 모델이 상주한다.
- 이미 쌓인 Ticket은 `uv run python -m soc.similar reindex`를 한 번 돌려야 검색된다.

## 범위 밖

- `kind` 인자와 Case를 별도 point로 넣는 것, Case 요약·Incident 본문의 임베딩
- 상태가 바뀔 때 payload를 갱신하는 것(payload는 비운다), 색인 누락의 자동 감지
- 에이전트 판정 사례가 L1 자동 종결(D-025)에 미치는 영향의 구조적 차단(이번에는 프롬프트 수준)
- 지난 Ticket의 보관 기간·삭제, `ticket_branch`와 두 컬렉션의 통합
- `l3` 허용, 사람이 `dismissed`로 닫은 Incident를 `human`으로 보는 것

## 완료 기준

- [ ] `ticket_id` 검색과 `query` 검색이 유사도 순 결과를 돌려주고, 가짜 임베더와 Qdrant 테스트 컬렉션으로 확인하는 테스트가 있다
- [ ] `ticket_id` 검색에서 자기 자신과 같은 Incident의 Ticket이 결과에 없는 테스트가 있다
- [ ] 모든 결과에 `decided_by`와 `case_id`가 정확히 들어가는 `db` 테스트가 있다(Case가 있으면 `human`, 없으면 `agent`, `dismissed`는 `agent`)
- [ ] 결과가 없을 때 빈 목록과 이유를 돌려주고, PostgreSQL에 없거나 판정이 없는 hit는 버리며, 예외로 죽지 않는 테스트가 있다
- [ ] `query` 길이·`limit`·이유 요약 길이·엔티티 개수 제한을 넘기지 않는 테스트가 있다
- [ ] 허용 목록에서 `l1`, `l2`만 쓸 수 있다(`l3` 거부 테스트)
- [ ] 색인: L1 판정 뒤 `verdict`가 있는 Ticket만 색인되고, 색인이 실패해도 L1 판정은 그대로이며, 임베딩 텍스트에 `verdict.reason`이 없는 테스트가 있다
- [ ] 재색인 명령이 판정이 있는 Ticket을 채우고 건수를 출력한다(`--recreate` 포함)
- [ ] `soc_agent_reader`가 지정 열만 읽고 `tickets.details`와 쓰기는 거부되는 `db` 테스트가 있다
- [ ] 임베더 잠금: 여러 스레드가 첫 호출을 동시에 해도 모델을 한 번만 올리는 테스트가 있다. 기존 도구 동작이 바뀌지 않는다
- [ ] Qdrant 환경변수나 임베더가 없으면 도구가 등록되지 않는다
- [ ] 프롬프트 `l1.md`, `l2.md`에 사용법 한 줄과 되먹임 경고가 들어갔다
- [ ] 실제 Qdrant로 검색이 되는 것을 `qdrant` 마커 테스트로 확인했다
- [ ] 실모델(`embedder` 마커)로 샘플 점수를 재서 `min_score` 기본값을 정했거나, 모델이 없으면 값을 임시로 두고 한계를 기록에 적었다(결과는 건수·범위로만)
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] `docs/decisions.md`에 D-053과 D-013 보완이 있고 `docs/security.md`에 한 줄이 있다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- **새 컬렉션과 색인 코드를 이 이슈에 포함한다.** 이슈 본문은 "새 저장·임베딩 코드 없음"이었지만, 지금 컬렉션(`ticket_branch`)에는 Incident에 붙은 `linked` Ticket만 있어 L1이 종결한 오탐을 참고할 수 없다. 이슈의 이유(L1이 같은 오탐을 매번 처음부터 분석함)를 풀려면 색인 범위가 먼저 넓어져야 한다. (추천은 색인을 별도 이슈로 분리하는 것이었으나 사람이 이번 이슈에 다 하기로 정했다. L2·L1 담당 확인 완료.)
- **판정·상태·시각·엔티티는 PostgreSQL에서 읽는다.** payload에 복사하지 않아 상태 변경 때 어긋나지 않는다. 이를 위해 `soc_agent_reader`에 열 단위 SELECT를 준다(0003의 "권한 없음"을 이 열에 한해 바꾼다, D-053).
- **색인 대상·시점:** `verdict`가 있는 Ticket, L1 판정 적용 직후 같은 프로세스. 실패는 경고만 남기고 재색인 명령으로 복구한다. 별도 주기 스윕은 쓰지 않는다.
- **임베딩 텍스트에 판정 이유를 넣지 않는다.** 질의 쪽에 이유가 없어 같은 종류의 텍스트끼리 비교하고, LLM이 쓴 문장이 검색 순위를 좌우하지 않게 한다.
- **`kind` 인자를 없앤다.** 이슈 본문의 입력 명세와 달라진 점이다. 결과는 항상 Ticket 단위이고 `case_id`와 `decided_by`로 구분한다.
- **`decided_by`는 Incident에 Case가 있으면 `human`, 그 밖에는 `agent`.** `dismissed`는 `agent`다. 지금 Case를 만드는 코드가 확인한 범위에서 보이지 않아 실데이터에서는 전부 `agent`일 수 있다. 테스트는 DB에 Case를 직접 넣어 확인한다.
- **현재 Incident의 다른 Ticket은 결과에서 뺀다**(`ticket_id` 검색만 가능).
- **임베더는 실행기가 한 번 만들어 주입한다.** 핸들러가 호출마다 만들거나 프로세스 전역 상태를 쓰는 안은 비용과 D-049 때문에 택하지 않았다. 도구 없이 저장 벡터만 쓰는 안은 L1의 `new` Ticket에 쓸 수 없어 택하지 않았다.
- **되먹임 완화는 프롬프트 수준이다.** 에이전트 판정 사례도 `decided_by`로 구분해 보여 주고, "에이전트 판정만으로 benign 확신도를 올리지 않는다"를 프롬프트에 넣는다. D-025의 자동 종결을 구조적으로 막지는 못한다(D-053 메모).
- **`min_score`·`limit` 기본값은 실모델로 샘플 점수를 재서 정한다.**
- 결정 목록: D-053 추가, D-013 메모 보완. `decisions.md`의 기존 충돌 표식과 D-049/D-050 중복은 건드리지 않는다.

## 바뀐 점

- 2026-11-13 · 읽기 권한 `tickets` 열에 `alert_ids`를 더했다. `ticket_id` 검색이 Ticket의 Alert 제목으로 질의 텍스트를 만들어야 하는데 Ticket과 Alert의 연결이 이 열뿐이다. D-053의 열 목록도 같이 고쳤다.
- 2026-11-13 · `BgeM3Embedder`가 macOS·Linux에서 Hugging Face 캐시(심링크)로는 모델을 못 여는 문제를 이 이슈에서 고친다(사람이 정함). 이슈 밖 문제였으나 `reindex`와 실행기의 첫 임베딩이 실패해 이 이슈의 색인이 동작하지 않는다. `hf_hub_download(local_dir=…)`로 `HF_HOME/soc-onnx/<모델>/<revision>`에 실제 파일로 받는다. 새 설정 키는 없다. 범위에 `src/soc/store/embedder.py`와 D-044 메모가 더해진다.
