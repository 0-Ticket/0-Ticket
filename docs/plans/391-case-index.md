---
issue: 391
date: 2026-11-27
owner: Interludeal
supersedes: []
---

# 승인된 Case를 전용 벡터 컬렉션에 색인하기

## 목표

Incident를 승인하면 만들어지는 Case가 Ticket 컬렉션과 별도인 Qdrant 컬렉션(`confirmed_cases`)에 point 하나로 색인된다. 승인 트랜잭션에는 색인 대기 행만 남기고, l2 단계 워커가 Qdrant에 쓴다. Qdrant가 죽어 있어도 승인은 성공하고 색인은 복구 뒤 반영된다. 기존 Case 백필·점검·재색인 명령을 둔다. 검색 도구(#392)와 L3 프롬프트(#393)는 이 색인을 읽는다.

## 방법

1. **패키지 `src/soc/case_index/`.** 워커는 l2 단계에서 돌지만 소비자는 L3 도구(#392)와 승인 API라서 `soc/l2/`·`soc/l3/` 밖에 둔다.
   - `__init__.py`: `build_worker`만 지연 import한다(`l2/branch/__init__.py`와 같은 방식).
   - `source.py`: 가벼운 상수와 SQL만 둔다. `PURPOSE = "confirmed_cases"`, `point_id(case_id)`(`cas_`를 뗀 UUID), `LATEST_ARTIFACT_SQL`. onnxruntime·qdrant 클라이언트·L2 runtime을 import하지 않는다.
   - `outbox.py`: `enqueue(conn, case_id)`. psycopg만 import한다.
   - `text.py`: 색인 텍스트 빌더.
   - `index.py`: `index_one`, 워커, `reindex`, `check`, `build_worker`.
   - `__main__.py`: `python -m soc.case_index check | reindex [--recreate]`.
2. **마이그레이션 `0310_case_index_jobs.sql`.** D-035 대역이 아니라 현재 최신 번호(0309) 다음을 쓴다.
   ```
   case_index_jobs(
     case_id text PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
     indexed_at timestamptz,                    -- NULL이면 대기
     attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
     last_error text,                           -- 예외 클래스 이름만
     next_attempt_at timestamptz NOT NULL DEFAULT now(),
     created_at timestamptz NOT NULL DEFAULT now())
   ```
   - 기존 `cases`마다 대기 행을 넣는다(0306이 Ticket에 한 방식).
   - `soc_agent_reader`에는 권한을 주지 않는다(읽는 쪽은 #392).
3. **승인 쓰기.** `ui_write.approve_incident`가 `cases` INSERT 직후, 같은 `conn.transaction()` 안에서 `enqueue(conn, case_id)`를 부른다. `reject_incident`와 `_record`·응답 모양은 그대로다. 대기 행 INSERT가 실패하면 승인 전체가 롤백된다.
4. **워커 `case_index`(단계 `l2`).** `[executor.l2] workers` 맨 뒤에 `soc.case_index:build_worker`를 등록한다.
   - `poll`: `indexed_at IS NULL AND next_attempt_at <= now()`를 `created_at, case_id` 순으로 집는다.
   - `handle`: Case와 최신 Artifact를 읽어 텍스트를 만들고, 임베딩해 `confirmed_cases`에 upsert한다(point ID는 `case_id`에서 `cas_`를 뗀 값, payload는 `{}`). `CollectionMissing`이면 `ensure_collection` 뒤 다시 넣는다. 성공하면 `indexed_at = now()`이다.
   - 실패하면 `attempts + 1`, `last_error = 예외 클래스 이름`, `next_attempt_at = now() + min(30초 × 2^(n−1), 10분)`이다(n은 갱신 후 `attempts`). 소진·포기 상태는 없고 `resume` 명령도 없다.
   - 텍스트가 불변이고 upsert가 멱등이라 advisory lock은 쓰지 않는다. 포기 상태가 없어서 `last_error`는 `check`로 보인다.
5. **색인 텍스트.** 라벨 붙은 줄을 아래 순서로 쓴다. 빈 값은 줄을 생략하고, 공백은 `" ".join(value.split())`로 접는다.
   ```
   title: …
   summary: …
   cause: …
   impact: …
   further_risk: …
   technique: <기법 이름>     (줄마다 하나)
   ```
   - 상한은 임베더와 별도다. 필드마다 1,000자, 기법은 최대 10줄, 전체 4,000자다(초안값. 개발 중 실모델로 손제작 Case 몇 건의 길이를 확인하고 "바뀐 점"에 건수로 적는다).
   - `title`·`summary`는 `cases`에서, `cause`·`impact`·`further_risk`·기법은 승인 당시 Artifact에서 읽는다. 기법 이름은 `artifact.techniques[].name`을 바로 쓴다(`attack_techniques`를 다시 찾지 않는다. ID는 넣지 않는다).
   - 넣지 않는 것: 타임라인, 근거 ID, 엔티티 값, 권고 조치, 반려 이력, Artifact `summary`(승인 때 Case 요약으로 복사된 같은 문장).
6. **승인 당시 Artifact.** `SELECT … FROM incident_artifacts WHERE incident_id = %s ORDER BY analysis_round DESC LIMIT 1`이다. `incident_reviews`는 읽지 않는다. 근거는 confirmed Incident를 재분석하는 경로가 없다는 점이다. `incidents.status`를 쓰는 곳은 모두 `confirmed`를 건드리지 않는다.
   - `ui_write.py:26-27,43`
   - `analyze/store.py:92-97,154-159`
   - `analyze/worker.py:56-57,72-73`
   - `branch/store.py:19,69-71,89-91`
   - Artifact 없이 `awaiting_review`가 되는 경로도 없다(`analyze/store.py:118-124`).
   - Artifact가 없는 Case(`dev_seed`나 직접 SQL로만 생긴다)는 `title`·`summary`만으로 색인한다.
7. **임베더 공유.** 워커는 `soc.l2.branch.runtime.get_service(settings).embedder`를 쓴다(`lru_cache`, 분류 색인 워커와 같은 인스턴스). 상주 모델은 둘로 유지한다. 새 명령은 별도 프로세스라 자기 임베더를 만든다. L2 담당이 공용 임베더를 `soc.store`로 옮기자고 하면 이 계획을 다시 연다.
8. **명령.**
   - `check`: `cases`(전체), `missing`(대기 행은 있는데 point 없음, `point_payload`가 `None`), `no_job`(대기 행 없는 Case), `pending`(`indexed_at IS NULL`), `no_artifact`를 출력한다. `missing`·`no_job`·`pending` 중 하나라도 있으면 종료 코드 1이다. `no_artifact`는 정보 표시만 한다.
   - `reindex [--recreate]`: 모든 Case를 돌며 없는 대기 행을 만들고, 컬렉션을 비웠다면 `indexed_at`을 초기화해 순서대로 색인한다. 결과는 `processed`·`succeeded`·`failed` 건수다. 실패가 있으면 종료 코드 1이다.
   - 명령 오류는 예외 종류만 출력한다(`l2/branch/index.py:177`과 같다).
9. **결정 기록.** `docs/decisions.md`에 D-084와 기록 한 줄을 더한다.

## 바꿀 곳

- `src/soc/db/migrations/0310_case_index_jobs.sql`: 대기 표와 기존 Case 백필.
- `src/soc/case_index/`(새 패키지): 위 구성.
- `src/soc/api/ui_write.py`: `approve_incident`에 `enqueue` 한 줄과 import. **승인 API 담당 확인 필요.**
- `config/default.toml`: `[executor.l2] workers` 맨 뒤에 한 줄. **L2 담당 확인 필요.**
- `docs/decisions.md`: D-084와 기록 한 줄. **팀 합의 필요.**
- 기대값만 고치는 기존 테스트(지우거나 건너뛰지 않는다).
  - `tests/test_agent_executor.py::test_default_config_executor_values`(기본 워커 목록, 가짜 워커 사전)
  - `tests/test_pipeline_db.py`의 `l2_resolver`(새 경로 가짜)
  - `tests/test_db_tables.py`(마이그레이션 목록, 표 집합)
  - `tests/test_api_review.py`(승인은 대기 행 하나, 반려는 없음, 롤백이면 없음)
- 새 테스트와 `tests/fixtures/case_index/`(손으로 만든 샘플): Artifact가 둘인 Incident, Artifact 없는 Case, 긴 필드 Case.

## 다른 코드와 맞물리는 곳

- **새 표 `case_index_jobs`.** 마이그레이션이 API 코드보다 먼저 적용돼야 한다. 없으면 승인이 실패한다.
- **승인 트랜잭션(`approve_incident`).** 승인 API 담당 코드다. 한 줄만 더하고 응답·`reject_incident`은 바꾸지 않는다.
- **`[executor.l2] workers`.** L2 담당 설정이다. 새 워커 한 줄만 더한다.
- **L2 함수 의존.** `get_service`·`BranchService`의 모양이 바뀌면 새 워커가 영향을 받는다. L2 파일은 고치지 않는다.
- **새 Qdrant 컬렉션 `confirmed_cases__<모델>__<digest>`.** 기존 `ticket_branch`·`ticket_verdicts`는 바꾸지 않는다. `search_similar_cases`도 그대로다.
- **#392 계약(다음 이슈와의 약속).**
  1. 용도 이름은 `soc.case_index.source.PURPOSE = "confirmed_cases"`다. 컬렉션은 `VectorStore(PURPOSE, embedder, settings)`로 연다(D-031, 같은 모델·revision이라 질의 벡터가 호환된다).
  2. point ID는 `case_id.removeprefix("cas_")`, payload는 `{}`다. hit에서 `"cas_" + point_id`로 되돌려 PostgreSQL에서 다시 확인한다(D-013). 대기 중이거나 실패한 Case는 검색에 나오지 않는다.
  3. 승인 당시 Artifact는 `source.LATEST_ARTIFACT_SQL`로 고른다. `incident_artifacts`의 SELECT만 필요하고 `incident_reviews`는 필요 없다. confirmed Incident가 재분석되지 않는다는 불변식을 docstring에 적는다. 이 재분석을 만들게 되면 기준을 다시 정한다.
  4. `source.py`·`outbox.py`는 무거운 것을 import하지 않는다.
  5. 컬렉션이 없으면 `CollectionMissing`이다. #392는 D-053처럼 `no_index`로 다룬다.
  6. 색인은 승인 직후가 아니라 워커 라운드(기본 10초) 뒤에 생긴다.
- **파이프 준비 점검.** `pipeline/check.py`는 바꾸지 않는다. Qdrant·임베더 점검은 `search_similar_cases`가 l1·l2에 허용될 때만 돈다(`check.py:118`). 이 허용을 `config/local.toml`에서 빼면 점검은 SKIP인데 분류 색인(#370)과 이 워커는 Qdrant가 필요하다. 이 틈은 #370부터 있었고 기술 부채로 기록한다.

## 범위 밖

- 검색 도구(#392), L3 프롬프트(#393), Case 상태 변경 API.
- 활성화 파이프(D-054)에 L3를 붙이는 일, L3 뉴스 선택.
- 분류·유사 사례 임베더 인스턴스를 하나로 합치기(기술 부채).
- `pipeline/check.py` 수정, `docs/architecture.md` 수정.
- 소진 상태와 `resume` 명령.
- 쓰지 않게 된 옛 컬렉션을 찾아 지우는 자동화(사람이 Qdrant에서 지운다).

## 완료 기준

- [ ] Incident를 승인하면 같은 트랜잭션에 대기 행이 생기고, l2 단계 워커가 돈 뒤 컬렉션에 그 Case의 point가 있다.
- [ ] Qdrant를 쓸 수 없어도 승인은 성공하고, 쓸 수 있게 되면 다음 라운드에 색인된다.
- [ ] 반려(`reject_incident`)는 대기 행을 만들지 않는다.
- [ ] 색인 텍스트에 정한 항목만 들어가고 타임라인·근거 ID·엔티티 값·반려 사유는 없다(가짜 임베더가 받은 문장으로 확인).
- [ ] 재색인 명령이 기존 Case를 모두 채우고, 점검 명령이 빠진 Case 수를 보여 준다.
- [ ] 승인 트랜잭션이 롤백되면 대기 행도 없고, 대기 행 INSERT가 실패하면 승인도 실패한다.
- [ ] 같은 Case를 워커가 두 번 돌려도 point는 하나이고, 색인된 Case는 다시 poll되지 않는다.
- [ ] 실패하면 `attempts`·`last_error`(예외 이름만)·`next_attempt_at`이 기록되고, 백오프 전에는 poll되지 않으며, Qdrant가 돌아오면 색인된다.
- [ ] Artifact가 둘 이상이면 최신만 쓰고, Artifact가 없는 Case는 제목·요약만으로 색인되며 `check`가 `no_artifact`를 보인다.
- [ ] `check`가 `missing`·`no_job`·`pending`·`no_artifact`를 보이고 이상이면 종료 코드 1이다. `reindex [--recreate]`가 대기 행 없는 Case까지 채운다.
- [ ] 새 워커가 임베더를 새로 만들지 않고 분류 서비스의 인스턴스를 쓴다(테스트로 같은 인스턴스 확인).
- [ ] `source`·`outbox` import가 onnxruntime·`qdrant_client`를 끌어오지 않는다.
- [ ] 마이그레이션 백필이 기존 Case마다 대기 행을 만들고, `soc_agent_reader`에는 권한이 없다.
- [ ] 기대값만 고친 기존 테스트 4개를 개발 기록에 적는다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과. 대상 DB·Qdrant 테스트는 `uv run pytest -m "db or qdrant"`로 확인한다.
- [ ] 새 환경변수·설정 키 없음(`.env.example` 변경 없음).
- [ ] `docs/decisions.md`에 D-084와 기록 한 줄, `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록.

**테스트 구성**

| 마커 | 대상 |
|---|---|
| 없음(기본) | 텍스트 빌더(순서·상한·금지 항목), 백오프 계산, import 가벼움 |
| `db` | 승인→대기 행, 반려→없음, 롤백, 최신 Artifact 선택, Artifact 없는 Case, 워커 poll·handle(가짜 저장소), 실패·백오프, 백필, `reindex`·`check` 건수, 읽기 역할 권한 없음 |
| `qdrant` | 실제 Qdrant로 point 왕복(빈 payload·ID 규칙), `reindex --recreate` 뒤 `check` 이상 없음, `CollectionMissing` 복구 |

`embedder` 마커 테스트는 새로 두지 않는다. 로컬 `qdrant` 마커는 `QDRANT_URL=http://127.0.0.1:6333`이어야 한다.

## 토론으로 정한 것

- 이름·위치: 용도 `confirmed_cases`, 테이블 `case_index_jobs`, 패키지 `src/soc/case_index/`. 이슈 본문의 `soc.l2.branch.index` 모양 대신 l2·l3 밖에 둔다(소비자가 L3 도구와 API라서).
- 마이그레이션 번호: `0310`. D-035 대역(L2 0200대)과 맞지 않지만 0303~0309도 03xx를 이어 썼고, 대역 안 번호는 "더 작은 번호" 경고를 낸다.
- 승인 당시 차수: 그 Incident의 최신 Artifact. Artifact 없는 Case는 제목·요약만으로 색인하고 `check`에 `no_artifact`로 보인다.
- 색인 텍스트: 라벨 줄 형식, 기법 이름은 Artifact의 `name`을 그대로 쓰고 ID는 뺀다, 필드 1,000자·기법 10줄·전체 4,000자 상한을 임베더 절단과 별도로 둔다. 임베더가 8192토큰에서 뒤를 조용히 자르면 뒤 필드가 밀려나서다.
- 대기 기록: revision 없이 단순하게 두고, 포기 상태 없이 백오프로 무한 재시도한다. 소진 시 상태를 두면 "쓸 수 있게 되면 다음 라운드에 색인된다"는 완료 기준이 장기 장애에서 깨지기 때문이다.
- 임베더: 분류 서비스의 임베더를 공유한다(둘 유지, 셋으로 늘리지 않음). L2 담당이 공용 임베더를 `soc.store`로 옮기자고 하면 계획을 다시 연다.
- 백필: 마이그레이션이 기존 Case마다 대기 행을 넣고, `reindex`는 이후 직접 INSERT된 Case와 컬렉션 재생성을 담당한다.
- 파이프 점검: 항목을 더하지 않는다. `needs_vector` 전제의 틈은 기술 부채다.
- 결정 번호: D-013 문구 조정과 D-053과의 차이(판정 이유는 임베딩하지 않지만 Case 색인은 L2의 분석 문장을 임베딩한다)를 새 결정 D-084로 적고, D-013·D-053 행 본문은 고치지 않는다(D-082가 D-076을 대체한 선례).
- 담당 합의: 승인 API 담당(`ui_write.py`)과 L2 담당(`[executor.l2]`, `get_service` 의존)의 확인은 PR 리뷰에서 받는다. 그때까지 계획의 "확인 필요" 표시를 유지한다.

## 바뀐 점

- 2026-11-27 · 텍스트 상한(필드 1,000자·기법 10줄·전체 4,000자)의 토큰 수는 확인하지 못했다. bge-m3 토크나이저 파일이 로컬에 없었고 내려받지 않았다. 상한은 초안값 그대로 두었다.
