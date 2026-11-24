---
issue: 370
date: 2026-11-24
owner: Juhyeok0603
plan: 370-l2-ticket-candidates.md
supersedes: []
---

# L2 Ticket 유사도 후보 분류 개발 기록

## 한 일

- 분류용 임베딩 텍스트를 손제작 같은 사건·다른 사건 샘플로 먼저 고정했다. Ticket/Alert 제목·룰·역할이 표시된 엔티티·Alert/Event 요약·Hunt 가설을 길이 제한해 합치고 모델 판정 이유를 제외한다.
- `l2_ticket_index_jobs`를 만들고 기존 Ticket을 백필했다. Ticket 생성·L1 판정·L3 갱신·Incident 연결 시 같은 DB 트랜잭션에서 revision을 올린다. 별도 색인 워커가 Ticket별 advisory lock으로 Qdrant 쓰기를 직렬화한다.
- `ticket_branch`에서 하한 이상인 linked Ticket을 끝까지 읽고 DB의 현재 소속·상태·버전을 다시 확인한다. 동점 결과의 offset 페이지가 겹치면 전체 검색으로 누락을 복구한다. Incident별 최고 점수 Ticket을 대표로 보존하며 그래프 조회는 그 Incident에만 제한한다.
- 후보 5개씩, 주기당 모델 호출 3회까지 검토한다. 중간 결과와 최종 비교 진행 위치는 Ticket에 남겨 다음 주기에 잇는다. 색인·검색·그래프·모델·저장 오류는 신규 Incident로 바꾸지 않고 5분 간격 3회 실패 뒤 L2 보류로 전환한다.
- `python -m soc.l2.branch.index check`, `reindex --recreate`, `resume <ticket_id>`를 추가했다. `resume`은 L2가 보류한 Ticket만 재개한다. 오류는 DB 접속 정보를 출력하지 않고 종류만 표시하며 실패 상태 코드로 종료한다. Incident 상세 API와 화면은 벡터 전용 연결과 그래프 경로 없음, 기각된 벡터 후보를 구분한다.
- 실제 bge-m3로 손제작 5건의 점수를 측정했다. 같은 웹셸 사건 4건의 모든 쌍은 0.772571~0.986413이어서 하한을 0.7725로 정했다. 다른 SQLi 사건도 웹셸 사례와 0.902024로 유사하므로 L2 판단이 분리에 필요하다.
- 분류 텍스트 5건은 178~211자, 72~85 토큰이었다. 로컬 ONNX 임베딩은 첫 건 모델 로드 포함 5.379초, 이어진 4건은 건당 0.122~0.162초였다. L2 호출은 후보 수에 따라 0~3회/주기이며, 실제 LLM 입력 토큰·요금·지연은 provider 설정이 없어 측정하지 못했다.

## 계획과 달라진 점

목표·범위·완료 기준 변경은 없다. `branch_decision` 계약은 이미 `new`일 때 `similar_ticket_ids`를 빈 배열로 제한하고 있어 원본과 생성 파일을 수정하지 않았다. 실행기 코드는 건드리지 않고 기본 설정의 워커 순서만 바꿨다.

## 다음 사람이 알아야 할 것

- #370 이슈의 확정 댓글과 계획 파일은 같은 방향이다. 이슈 본문의 미결 항목은 계획 파일의 토론으로 정했다.
- `ticket_verdicts`는 L1·L2 유사 사례 검색용이며 이번 분류 색인과 별개다.
- 과거 Ticket·Incident 관계는 자동으로 바꾸지 않는다. 배포 뒤 `reindex --recreate` 완료와 `check`의 missing/stale 0을 확인해야 분류가 재개된다.
- `config/local.toml`이 `[l2.branch]`를 덮어쓰면 새 하한·호출·실패 설정을 확인해야 한다.
- 실제 LLM을 쓰는 수동 회귀 테스트(`tests/test_l2_scenarios_llm.py`)는 `LLM_API_KEY`가 없어 실행하지 못했다. 손제작 36건의 그래프 회귀, 모델 출력 검증, DB 저장 테스트와 실제 임베딩 재현율 테스트로 코드 경로를 확인했다.
- 화면 문구를 바꾼 PR에는 사람이 전·후 스크린샷을 붙여야 한다(D-075).

## 확인 방법

- `uv run pytest -q`: 2,694건 통과, DB/Qdrant/Embedder 705건은 별도 마커.
- `uv run pytest -q -m embedder tests/test_l2_vector_calibration.py`: 1건 통과.
- `pnpm contracts:check`, `pnpm lint`, `pnpm test`(123건), `pnpm build`: 통과. 린트의 기존 Fast Refresh 경고 1건과 빌드 번들 크기 경고가 남았다.
- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest -q -m "db or qdrant"`: 689건 통과. Qdrant 클라이언트의 서버 버전 확인 경고 1건이 남았다.
- db 마커 테스트는 `DATABASE_URL`의 호스트를 `127.0.0.1`로 둬야 한다. Windows에서 `localhost`는 `::1`로 먼저 풀리고 compose의 postgres는 `127.0.0.1`에만 바인딩해서, psycopg가 타임아웃 없이 무한 대기한다. `QDRANT_URL`도 같은 이유로 `http://127.0.0.1:6333`이다.
