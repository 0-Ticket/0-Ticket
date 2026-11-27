---
issue: 391
date: 2026-11-27
owner: Interludeal
plan: 391-case-index.md
supersedes: []
---

# 승인된 Case를 전용 Qdrant 컬렉션에 색인하고, l2 단계 워커가 대기 행을 읽어 채우게 했다

## 한 일

- Incident를 승인하면 `cases`를 만드는 같은 트랜잭션에서 새 표 `case_index_jobs`(0310)에 Case별 대기 행이 한 줄 생긴다(`ui_write.approve_incident`). 반려는 만들지 않는다. 대기 행을 만들지 못하면(표가 없는 경우 등) 승인이 롤백된다.
- 새 패키지 `src/soc/case_index/`의 워커 `case_index`(단계 `l2`)가 대기 행을 읽어 Qdrant 용도 `confirmed_cases` 컬렉션에 Case당 point 하나를 쓴다. point ID는 Case ID에서 `cas_`를 뗀 UUID이고 payload는 비어 있다. Qdrant가 죽어 있어도 승인은 성공하고, 실패한 행은 `attempts`·`last_error`(예외 클래스 이름만)·`next_attempt_at`에 남아 30초에서 시작해 최대 10분 간격으로 계속 다시 시도한다. 포기하는 상태는 없다.
- 색인 텍스트는 `title`·`summary`(Case), `cause`·`impact`·`further_risk`와 `technique`(승인 당시 = 그 Incident의 최신 Artifact, 기법은 Artifact에 저장된 `name`) 라벨 줄이다. 필드마다 1,000자, 기법 이름은 줄마다 80자에 10줄, 전체 6,000자로 자른다. Artifact가 없는 Case는 제목·요약만으로 색인한다.
- `uv run python -m soc.case_index check`는 `cases`·`missing`·`no_job`·`pending`·`no_artifact` 건수를 낸다. `reindex [--recreate]`는 모든 Case를 다시 색인하고 `processed`·`succeeded`·`failed`를 낸다.
- 마이그레이션이 기존 `cases`마다 대기 행을 넣어 배포 뒤 워커가 채운다. `[executor.l2] workers` 맨 뒤에 `soc.case_index:build_worker`를 등록했다. 워커는 분류 색인 워커와 같은 임베더(`soc.l2.branch.runtime.get_service(...).embedder`)를 쓴다. 새 환경변수·설정 키는 없다.
- 결정은 D-084(`docs/decisions.md`)다. 승인 API 담당(`ui_write.py`)과 L2 담당(`[executor.l2]`, `get_service` 의존)의 확인은 PR 리뷰에서 받는다.

## 계획과 달라진 점

- **기대값을 고친 기존 테스트가 4개가 아니라 5개다(사람이 승인함).** 계획의 4개(`test_agent_executor.py`, `test_pipeline_db.py`의 `l2_resolver`, `test_db_tables.py`, `test_api_review.py`)에 더해 파이프 담당(#316) 파일 `tests/test_pipeline_main.py`도 고쳤다. 파이프 담당 확인은 PR 리뷰에서 받는다. `make_resolver`가 워커 경로에 단계 이름(`l1`·`l2`…)이 들어 있다고 가정하는데 `soc.case_index:build_worker`에는 없어서, `soc.case_index`를 `l2`로 알려 주는 한 줄과 워커 수 6→7, `l2` 개수 3→4만 바꿨다. 테스트를 지우거나 건너뛰지 않았다.
- **`reindex`는 모든 대기 행을 초기화하고 전부 다시 처리한다.** `--recreate` 없이도 그렇다(계획은 "컬렉션을 비웠다면 초기화"). 그래야 `check`가 `missing`으로 보인 잃어버린 point를 `reindex`만으로 채운다. 백오프는 무시한다(운영자가 직접 돌린다). `attempts`도 0으로 되돌아간다.
- **`check`의 `missing`은 "색인했다고 기록됐는데 point가 없다"이다.** 대기 중(`pending`)인 행은 point를 조회하지 않는다(어차피 없을 것이다). 컬렉션이 없으면 색인 완료 행은 모두 `missing`이다. 이상으로 치는 것은 `missing`·`no_job`·`pending`이고 `no_artifact`는 정보 표시다(종료 코드 1이 아니다).
- **마이그레이션에 부분 인덱스 `case_index_jobs_pending_idx`를 더했다.** 계획의 표 정의에는 없다. 워커 `poll`이 `indexed_at IS NULL`만 `created_at, case_id` 순으로 집어서다.
- **텍스트 전체 상한을 4,000자에서 6,000자로 올렸다(사람이 정함).** 4,000자일 때는 다섯 필드가 모두 가득 차면 `further_risk`와 기법 줄이 잘렸다. 기법 이름 줄마다 80자 상한(`MAX_TECHNIQUE_CHARS`)을 새로 더했다. 기법 이름이 필드 상한(1,000자)까지 가면 6,000자도 넘기 때문이다. 이제 최악의 길이(약 5,970자)가 전체 상한 아래라 전체 상한은 안전장치다. `tests/test_case_index.py`가 가득 찬 샘플에서 아무것도 잘리지 않는 것을 확인한다.
- 성공하면 `last_error`는 지우고 `attempts`는 그대로 둔다(몇 번 만에 됐는지 남긴다). `enqueue`는 이미 있으면 `ON CONFLICT DO NOTHING`이다.
- `[executor.l2] workers`는 한 줄이 아니라 여러 줄 TOML 배열이 됐다(줄 길이 때문이다).
- 모든 로컬 DB 테스트는 `postgres:16-alpine`(로컬에 이미 있던 이미지)로 돌렸다. compose는 17.6이다.

## 다음 사람이 알아야 할 것

- **배포 순서: 마이그레이션 0310이 API 코드보다 먼저여야 한다.** 표가 없으면 승인이 실패한다(같은 트랜잭션이라 Case도 안 생긴다).
- **임베더.** 워커는 같은 프로세스(`python -m soc.agent`, 활성화 파이프)의 분류 색인 워커와 임베더를 공유한다. `python -m soc.case_index …`는 별도 프로세스라 모델을 하나 더 올린다(약 2.27GB, 모델이 없으면 내려받는다). `soc.case_index.index`가 L2 담당의 `get_service`에 의존한다. 그 모양이 바뀌면 워커가 영향을 받는다. L2 담당이 공용 임베더를 `soc.store`로 옮기자고 하면 계획을 다시 연다.
- **텍스트 상한.** 필드 1,000자·기법 이름 80자에 10줄·전체 6,000자다. 최악의 길이가 전체 상한보다 작게 상수를 정했고 테스트로 막아 둔다. 상수를 키우면(예: 필드 상한) 전체 상한이 다시 뒤 필드를 자를 수 있다. 값은 초안이고 실제 기법 이름 길이는 재지 않았다.
- **토큰 수는 확인하지 못했다.** bge-m3 토크나이저 파일(`soc-onnx/<모델 ID>/<revision>`)이 이 PC에 없었고, 지시대로 내려받지 않았다. 6,000자가 8192토큰 안인지는 샘플로 재지 않았다. 6,000자는 한국어로도 8192토큰보다 짧을 것으로 보이지만 숫자로 확인한 것이 아니다.
- **불변식.** 승인 당시 Artifact를 "그 Incident의 최신 Artifact"로 고르는 것은 confirmed Incident가 재분석되지 않는다는 전제다(DB가 강제하지 않는다). 재분석을 만들면 `source.py`의 `LATEST_ARTIFACT_SQL`과 이 색인을 다시 정해야 한다.
- **#392가 쓰는 것.** `soc.case_index.source`의 `PURPOSE`·`point_id`·`case_id_of`·`LATEST_ARTIFACT_SQL`(`incident_artifacts` SELECT만 필요, `incident_reviews` 불필요). 이 모듈과 `outbox`·`text`는 임베더·Qdrant·L2를 import하지 않고, `tests/test_case_index.py`가 새 프로세스에서 확인한다. 컬렉션이 없으면 `CollectionMissing`이다. 색인은 승인 직후가 아니라 워커 라운드(기본 10초) 뒤에 생긴다.
- **포기 상태가 없다.** 오래 실패하는 Case는 `check`의 `pending`과 `case_index_jobs.last_error`로 본다. 실행기 로그에는 예외 클래스 이름만 남는다. 설정이 틀려(`CollectionMismatch` 등) 계속 실패하면 10분마다 다시 시도한다.
- **dev_seed·직접 INSERT한 Case는 대기 행이 없다**(마이그레이션 뒤에 넣으면). `check`가 `no_job`으로 보이고 `reindex`가 채운다.
- **`config/local.toml`이 `[executor.l2] workers`를 따로 정의했으면** `soc.case_index:build_worker`를 직접 더해야 한다.
- **기술 부채 1: 파이프 준비 점검의 틈.** `pipeline/check.py`는 `search_similar_cases`가 l1·l2에 허용될 때만 Qdrant·임베더를 점검한다(`check.py:118`). 그 허용을 빼면 점검은 SKIP인데 분류 색인과 이 워커는 Qdrant가 필요하다. #370부터 있던 틈이고 이번에는 고치지 않았다.
- **기술 부채 2: 임베더 인스턴스가 둘로 따로 있다.** 분류 색인 워커(와 이 워커)가 쓰는 것과 유사 사례 서비스(`similar/runtime.py`)가 쓰는 것이다. 하나로 합치는 일은 범위 밖이다.
- 쓰지 않게 된 옛 `confirmed_cases__…` 컬렉션은 사람이 Qdrant에서 지운다(자동으로 찾거나 지우는 명령은 없다).
- **Windows에서 테스트를 돌릴 때** `PYTHONUTF8=1`이 필요하다(`test_api_ui.py`가 `read_text()`로 `ui_seed.json`을 읽어 cp949에서 실패한다. 이 이슈와 무관한 기존 문제). `DATABASE_URL`·`QDRANT_URL`의 호스트는 `127.0.0.1`로 둔다.
- **`poll` 순서 테스트가 부하 중 드물게 실패했다(조사함, 원인은 못 찾음).**
  - 증상: 전체 `-m db` 실행(약 800건)에서 `test_worker_polls_pending_jobs_in_order_up_to_the_limit`가 한 번 실패했다. `poll(2)`는 맞게 돌려준 직후 `poll(10)`이 빈 목록이었다. 다른 pytest를 같이 돌리며 poll 관련 테스트 4개를 병렬로 반복했을 때 100회 중 1회 실패했다(어느 테스트인지는 잡지 못했다). 나머지 99회와 단독 반복 8회는 통과했다.
  - 가설("파이썬 시각이 `next_attempt_at`·`created_at`에 들어가 DB 시계와 어긋난다")은 맞지 않았다. 두 열의 값은 코드에서 DB `now()`뿐이다(`index.py`의 백오프 `now() + make_interval`, `poll`의 `next_attempt_at <= now()`·`ORDER BY created_at`, `reindex`의 `next_attempt_at = now()`, 마이그레이션의 `DEFAULT now()`). 테스트도 `now()`뿐이고, 파이썬 시각(`to_datetime`)은 Incident·Artifact·Case 샘플 행에만 쓰인다. 호스트 시계를 ±약 10년 어긋나게 해도 poll·백오프가 같다는 테스트(`test_due_time_and_backoff_come_only_from_the_database_clock`)를 더했다.
  - 남은 후보(확인하지 못한 추정): PostgreSQL의 `now()`는 트랜잭션(자동 커밋 연결이면 문장) 시작 시각이라 연결마다 값이 다르다. 막 INSERT한 연결과 `poll`하는 연결의 `now()`가 아주 조금(1초보다 훨씬 작게) 어긋나면 `next_attempt_at <= now()`에서 행이 빠질 수 있다. VM의 CPU 사이 시계 차이나 시계가 잠깐 되돌아가는 일이 부하 때 나올 수 있다. 증거는 부하가 있을 때만 드물게 나왔다는 것뿐이다.
  - 한 일: 막 넣은 행을 바로 집는다고 가정한 테스트에 `make_due`(DB 시각의 1초 전으로 설정)를 넣고, `now()`로 "지금"을 정하던 곳을 `now() - interval '1 second'`로 바꿨다. 운영 코드는 바꾸지 않았다. 행을 한 번 놓쳐도 다음 라운드(기본 10초)에 집힌다.
  - 다시 나오면: 실패한 테스트 이름과 `poll` 전후의 `SELECT now(), next_attempt_at FROM case_index_jobs` 값을 먼저 본다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2780건 통과(832건은 마커로 제외).
- `uv run pytest -m db`(임시 PostgreSQL 16 컨테이너, 이 작업을 위해 따로 띄우고 끝낸 뒤 지움, 마지막 커밋 `c27d64c` 기준 전체): 784건 통과, 실패 2건, 오류 4건. **모두 `QDRANT_URL`이 없어서 난 것이다.** 오류 4건은 `tests/test_case_index_qdrant.py`의 fixture(`qdrant 테스트에는 QDRANT_URL이 필요하다`)이고, 실패 2건은 `tests/test_l2_branch_db.py`의 `qdrant` 마커가 붙은 기존 테스트(`test_branch_reindex_detects_missing_point_and_recovers`, `test_vector_candidate_uses_current_incident_and_rejects_stale_payload`)가 `StoreError: 환경변수 QDRANT_URL이 없다`로 실패한 것이다(#375·#389 기록과 같은 기존 실패). 그 밖의 실패는 없고, 부하 중 한 번 실패했던 `poll` 순서 테스트도 통과했다. CI에는 Qdrant 서비스가 있다.
- **`uv run pytest -m qdrant`는 돌리지 못했다.** 이 PC에 Qdrant가 떠 있지 않았고 이미지도 없었다. 대신 `tests/test_case_index_qdrant.py` 4건을 클라이언트만 메모리 모드(`QdrantClient(":memory:")`)로 바꾸는 임시 플러그인(커밋 안 함)으로 돌려 4건 통과했다. 실제 Qdrant 서버의 빈 payload 저장·Cosine 점수·없는 컬렉션 오류 해석은 CI에서 처음 확인된다.
- 주요 테스트
  - `tests/test_case_index.py`: 텍스트 형식·순서·금지 항목(타임라인·근거 ID·엔티티 값·기법 ID·Artifact 요약 없음)·필드·기법 이름·기법 줄 수 상한, 최악의 길이가 전체 상한(6,000자) 아래임, 다섯 필드와 기법 10줄이 가득 찬 샘플에서 아무것도 안 잘림, 전체 상한이 안전장치로 남음, 백오프 30→600초, point ID 규칙, `source`·`outbox`·`text`가 임베더·Qdrant·L2를 끌어오지 않음(새 프로세스), 워커가 분류 서비스의 임베더를 공유함, 실행기가 `soc.case_index:build_worker`를 풀 수 있음.
  - `tests/test_case_index_command.py`: 건수 출력, 종료 코드(`missing`·`no_job`·`pending`은 1, `no_artifact`는 0, 설정 오류 2), 오류는 예외 이름만.
  - `tests/test_case_index_db.py`(`db`): 마이그레이션 백필(0310만 뺀 폴더로 먼저 적용), 표 제약·cascade·읽기 역할 권한 없음, 최신 Artifact(1·3차 중 3차)·반려 사유·타임라인·엔티티 값이 텍스트에 없음, 두 번째 실행은 임베딩·쓰기 없음, Artifact 없는 Case는 제목만, 실패 시 예외 이름만 기록하고 30→60초 백오프(임베더·저장소를 못 만든 실패도 같게 기록), 백오프 전에는 `poll`이 안 집음, Qdrant가 돌아오면 색인되고 `last_error`가 지워짐, 호스트 시계가 ±약 10년 어긋나도 poll·백오프가 같음, 승인→대기 행→워커 색인, 대기 행 INSERT 실패 시 승인 롤백, 반려는 대기 행 없음, `check`·`reindex`(잃어버린 point·`--recreate`·실패·백오프 무시).
  - `tests/test_case_index_qdrant.py`(`qdrant`·`db`): 실제 Qdrant에서 빈 payload와 순위, `check`·`reindex`의 복구, 없는 컬렉션 생성, 승인된 Case 검색.
  - 기대값만 고친 기존 테스트: `test_agent_executor.py::test_default_config_executor_values`, `test_pipeline_db.py`의 `l2_resolver`, `test_db_tables.py`(마이그레이션 목록·표 집합), `test_api_review.py`(대기 행 단언 2개 추가), `test_pipeline_main.py`(`make_resolver`·워커 수).
- 손으로 만든 샘플: `tests/fixtures/case_index/cases.json`(Incident 4개, Artifact 4개, Case 3개 — Artifact가 둘인 Incident, Artifact 없는 Case, 긴 필드 Case, 승인 대기 Incident).
