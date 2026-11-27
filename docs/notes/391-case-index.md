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
- 색인 텍스트는 `title`·`summary`(Case), `cause`·`impact`·`further_risk`와 `technique`(승인 당시 = 그 Incident의 최신 Artifact, 기법은 Artifact에 저장된 `name`) 라벨 줄이다. 필드마다 1,000자, 기법 10줄, 전체 4,000자로 자른다. Artifact가 없는 Case는 제목·요약만으로 색인한다.
- `uv run python -m soc.case_index check`는 `cases`·`missing`·`no_job`·`pending`·`no_artifact` 건수를 낸다. `reindex [--recreate]`는 모든 Case를 다시 색인하고 `processed`·`succeeded`·`failed`를 낸다.
- 마이그레이션이 기존 `cases`마다 대기 행을 넣어 배포 뒤 워커가 채운다. `[executor.l2] workers` 맨 뒤에 `soc.case_index:build_worker`를 등록했다. 워커는 분류 색인 워커와 같은 임베더(`soc.l2.branch.runtime.get_service(...).embedder`)를 쓴다. 새 환경변수·설정 키는 없다.
- 결정은 D-084(`docs/decisions.md`)다. 승인 API 담당(`ui_write.py`)과 L2 담당(`[executor.l2]`, `get_service` 의존)의 확인은 PR 리뷰에서 받는다.

## 계획과 달라진 점

- **기대값을 고친 기존 테스트가 4개가 아니라 5개다.** 계획의 4개(`test_agent_executor.py`, `test_pipeline_db.py`의 `l2_resolver`, `test_db_tables.py`, `test_api_review.py`)에 더해 `tests/test_pipeline_main.py`도 고쳤다. `make_resolver`가 워커 경로에 단계 이름(`l1`·`l2`…)이 들어 있다고 가정하는데 `soc.case_index:build_worker`에는 없어서, `soc.case_index`를 `l2`로 알려 주는 한 줄과 워커 수 6→7, `l2` 개수 3→4만 바꿨다. 테스트를 지우거나 건너뛰지 않았다.
- **`reindex`는 모든 대기 행을 초기화하고 전부 다시 처리한다.** `--recreate` 없이도 그렇다(계획은 "컬렉션을 비웠다면 초기화"). 그래야 `check`가 `missing`으로 보인 잃어버린 point를 `reindex`만으로 채운다. 백오프는 무시한다(운영자가 직접 돌린다). `attempts`도 0으로 되돌아간다.
- **`check`의 `missing`은 "색인했다고 기록됐는데 point가 없다"이다.** 대기 중(`pending`)인 행은 point를 조회하지 않는다(어차피 없을 것이다). 컬렉션이 없으면 색인 완료 행은 모두 `missing`이다. 이상으로 치는 것은 `missing`·`no_job`·`pending`이고 `no_artifact`는 정보 표시다(종료 코드 1이 아니다).
- **마이그레이션에 부분 인덱스 `case_index_jobs_pending_idx`를 더했다.** 계획의 표 정의에는 없다. 워커 `poll`이 `indexed_at IS NULL`만 `created_at, case_id` 순으로 집어서다.
- 성공하면 `last_error`는 지우고 `attempts`는 그대로 둔다(몇 번 만에 됐는지 남긴다). `enqueue`는 이미 있으면 `ON CONFLICT DO NOTHING`이다.
- `[executor.l2] workers`는 한 줄이 아니라 여러 줄 TOML 배열이 됐다(줄 길이 때문이다).
- 모든 로컬 DB 테스트는 `postgres:16-alpine`(로컬에 이미 있던 이미지)로 돌렸다. compose는 17.6이다.

## 다음 사람이 알아야 할 것

- **배포 순서: 마이그레이션 0310이 API 코드보다 먼저여야 한다.** 표가 없으면 승인이 실패한다(같은 트랜잭션이라 Case도 안 생긴다).
- **임베더.** 워커는 같은 프로세스(`python -m soc.agent`, 활성화 파이프)의 분류 색인 워커와 임베더를 공유한다. `python -m soc.case_index …`는 별도 프로세스라 모델을 하나 더 올린다(약 2.27GB, 모델이 없으면 내려받는다). `soc.case_index.index`가 L2 담당의 `get_service`에 의존한다. 그 모양이 바뀌면 워커가 영향을 받는다. L2 담당이 공용 임베더를 `soc.store`로 옮기자고 하면 계획을 다시 연다.
- **텍스트 상한.** 다섯 필드가 모두 1,000자를 채우면 합이 4,000자를 넘어 뒤 필드와 기법 줄이 잘린다(전체 상한이 마지막에 자른다). 필드별 상한은 앞 필드가 길어도 뒤 필드가 밀려나지 않게 하려던 것인데, 모두 가득 찬 경우에는 그 효과가 줄어든다. 값은 초안이다.
- **토큰 수는 확인하지 못했다.** bge-m3 토크나이저 파일(`soc-onnx/<모델 ID>/<revision>`)이 이 PC에 없었고, 지시대로 내려받지 않았다. 4,000자가 8192토큰 안인지는 샘플로 재지 않았다. 4,000자는 한국어로도 8192토큰보다 훨씬 짧을 것으로 보이지만 숫자로 확인한 것이 아니다.
- **불변식.** 승인 당시 Artifact를 "그 Incident의 최신 Artifact"로 고르는 것은 confirmed Incident가 재분석되지 않는다는 전제다(DB가 강제하지 않는다). 재분석을 만들면 `source.py`의 `LATEST_ARTIFACT_SQL`과 이 색인을 다시 정해야 한다.
- **#392가 쓰는 것.** `soc.case_index.source`의 `PURPOSE`·`point_id`·`case_id_of`·`LATEST_ARTIFACT_SQL`(`incident_artifacts` SELECT만 필요, `incident_reviews` 불필요). 이 모듈과 `outbox`·`text`는 임베더·Qdrant·L2를 import하지 않고, `tests/test_case_index.py`가 새 프로세스에서 확인한다. 컬렉션이 없으면 `CollectionMissing`이다. 색인은 승인 직후가 아니라 워커 라운드(기본 10초) 뒤에 생긴다.
- **포기 상태가 없다.** 오래 실패하는 Case는 `check`의 `pending`과 `case_index_jobs.last_error`로 본다. 실행기 로그에는 예외 클래스 이름만 남는다. 설정이 틀려(`CollectionMismatch` 등) 계속 실패하면 10분마다 다시 시도한다.
- **dev_seed·직접 INSERT한 Case는 대기 행이 없다**(마이그레이션 뒤에 넣으면). `check`가 `no_job`으로 보이고 `reindex`가 채운다.
- **`config/local.toml`이 `[executor.l2] workers`를 따로 정의했으면** `soc.case_index:build_worker`를 직접 더해야 한다.
- **파이프 준비 점검의 틈.** `pipeline/check.py`는 `search_similar_cases`가 l1·l2에 허용될 때만 Qdrant·임베더를 점검한다(`check.py:118`). 그 허용을 빼면 점검은 SKIP인데 분류 색인과 이 워커는 Qdrant가 필요하다. #370부터 있던 틈이고 이번에는 고치지 않았다(기술 부채).
- **기술 부채.** 분류·유사 사례 임베더 인스턴스가 둘로 따로 있다(합치는 일은 범위 밖). 쓰지 않게 된 옛 `confirmed_cases__…` 컬렉션은 사람이 Qdrant에서 지운다.
- **Windows에서 테스트를 돌릴 때** `PYTHONUTF8=1`이 필요하다(`test_api_ui.py`가 `read_text()`로 `ui_seed.json`을 읽어 cp949에서 실패한다. 이 이슈와 무관한 기존 문제). `DATABASE_URL`·`QDRANT_URL`의 호스트는 `127.0.0.1`로 둔다.
- **전체 `-m db` 실행에서 한 번 실패한 테스트가 있다.** `test_worker_polls_pending_jobs_in_order_up_to_the_limit`가 `poll(2)`는 맞게 돌려준 직후 `poll(10)`이 빈 목록을 돌려줬다. 같은 테스트를 8번, 영향받는 DB 테스트 189건을 한 번 더 돌렸을 때는 모두 통과했다. 원인은 찾지 못했다(컨테이너 재시작·오류 없음). 다시 나오면 `poll`의 `next_attempt_at <= now()`와 시계를 먼저 본다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2777건 통과(829건은 마커로 제외).
- `uv run pytest -m db`(임시 PostgreSQL 16 컨테이너, 이 작업을 위해 따로 띄우고 끝낸 뒤 지움): 780건 통과, 실패 3건, 오류 4건. 오류 4건은 `QDRANT_URL`이 없어 나는 `tests/test_case_index_qdrant.py`의 fixture 오류이고, 실패 2건은 `tests/test_l2_branch_db.py`의 `qdrant` 마커가 붙은 기존 테스트가 같은 이유로 실패한 것이다(#375·#389 기록과 같은 기존 실패). 나머지 1건은 위의 `poll` 순서 테스트다. 영향받는 DB 테스트(`test_case_index_db.py`·`test_db_tables.py`·`test_api_review.py`·`test_pipeline_db.py`·`test_incident_reviews_db.py`·`test_similar_db.py`, `qdrant` 제외)는 따로 한 번 더 돌려 189건 통과했다.
- **`uv run pytest -m qdrant`는 돌리지 못했다.** 이 PC에 Qdrant가 떠 있지 않았고 이미지도 없었다. 대신 `tests/test_case_index_qdrant.py` 4건을 클라이언트만 메모리 모드(`QdrantClient(":memory:")`)로 바꾸는 임시 플러그인(커밋 안 함)으로 돌려 4건 통과했다. 실제 Qdrant 서버의 빈 payload 저장·Cosine 점수·없는 컬렉션 오류 해석은 CI에서 처음 확인된다.
- 주요 테스트
  - `tests/test_case_index.py`: 텍스트 형식·순서·금지 항목(타임라인·근거 ID·엔티티 값·기법 ID·Artifact 요약 없음)·필드·기법·전체 상한, 백오프 30→600초, point ID 규칙, `source`·`outbox`·`text`가 임베더·Qdrant·L2를 끌어오지 않음(새 프로세스), 워커가 분류 서비스의 임베더를 공유함, 실행기가 `soc.case_index:build_worker`를 풀 수 있음.
  - `tests/test_case_index_command.py`: 건수 출력, 종료 코드(`missing`·`no_job`·`pending`은 1, `no_artifact`는 0, 설정 오류 2), 오류는 예외 이름만.
  - `tests/test_case_index_db.py`(`db`): 마이그레이션 백필(0310만 뺀 폴더로 먼저 적용), 표 제약·cascade·읽기 역할 권한 없음, 최신 Artifact(1·3차 중 3차)·반려 사유·타임라인·엔티티 값이 텍스트에 없음, 두 번째 실행은 임베딩·쓰기 없음, Artifact 없는 Case는 제목만, 실패 시 예외 이름만 기록하고 30→60초 백오프(임베더·저장소를 못 만든 실패도 같게 기록), 백오프 전에는 `poll`이 안 집음, Qdrant가 돌아오면 색인되고 `last_error`가 지워짐, 승인→대기 행→워커 색인, 대기 행 INSERT 실패 시 승인 롤백, 반려는 대기 행 없음, `check`·`reindex`(잃어버린 point·`--recreate`·실패·백오프 무시).
  - `tests/test_case_index_qdrant.py`(`qdrant`·`db`): 실제 Qdrant에서 빈 payload와 순위, `check`·`reindex`의 복구, 없는 컬렉션 생성, 승인된 Case 검색.
  - 기대값만 고친 기존 테스트: `test_agent_executor.py::test_default_config_executor_values`, `test_pipeline_db.py`의 `l2_resolver`, `test_db_tables.py`(마이그레이션 목록·표 집합), `test_api_review.py`(대기 행 단언 2개 추가), `test_pipeline_main.py`(`make_resolver`·워커 수).
- 손으로 만든 샘플: `tests/fixtures/case_index/cases.json`(Incident 4개, Artifact 4개, Case 3개 — Artifact가 둘인 Incident, Artifact 없는 Case, 긴 필드 Case, 승인 대기 Incident).
