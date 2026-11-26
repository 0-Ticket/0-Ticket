---
issue: 375
date: 2026-11-26
owner: Pandyo
plan: 375-incident-review-reason.md
supersedes: [365-pen-screens.md, 384-incident-detail-design.md]
---

# Incident 반려 사유 저장·재분석 전달, 승인·반려 검토 이력

## 한 일

- 승인·반려 한 건마다 새 표 `incident_reviews`(0307)에 한 줄이 쌓이고, 같은 트랜잭션에서 `incidents.review_round`가 1 오른다. 기본키는 자동 증가 정수이고 ID 접두사가 없다.
- `POST /api/incidents/{id}/reject`가 선택 본문 `{reason?}`을 받는다(공백을 자르고, 빈 값은 NULL, 500자 초과·제어문자는 422). 본문이 없어도 된다. 승인은 본문이 없다.
- L2 조사 입력에 `data.rejection`(`{reason, decided_at}` 또는 null)이 생겼다. 가장 최근 검토가 반려이고 그 뒤 성공한 Artifact가 없을 때만 값이 있다. `l2_investigate.md`에 데이터 취급 지시를 더했다.
- `IncidentDetail.reviews[]`(결정·사유·처리한 사람·`review_round`·`analysis_round`·시각, `id` 순, `id`는 안 냄)를 `incident.read`로 보여 준다.
- 화면: 반려 버튼이 `<dialog>`를 열고(선택 사유 `<textarea>` 500자), 분석 이력 타임라인에 반려·승인 이벤트가 라운드 사이에 보인다. 사유는 텍스트로만 표시한다.

## 계획과 달라진 점

- 없음. 계획 파일의 "바뀐 점"도 비어 있다.
- 작은 선택: 화면의 사유 앞뒤 공백은 보내기 전에 한 번 더 자른다(서버도 자른다). 검토 이벤트의 `key`는 `review_round`다(한 Incident 안에서 유일, `UNIQUE (incident_id, review_round)`).
- 이벤트 배치 규칙: `analysis_round` 이하인 가장 큰 라운드 바로 위, 그런 라운드가 없으면 맨 아래. 같은 자리면 나중 것이 위다(`history-tab.tsx`의 `placeReviews`).

## 다음 사람이 알아야 할 것

- **한도 없음.** 반려를 반복하면 재분석 LLM 비용이 든다. D-028의 `review_round` 한도(`human_handling`)는 만들지 않았다(D-082, 후속).
- `incident_reviews`는 `soc_agent_reader` 권한이 없다. 이 표를 에이전트 도구에 열려면 사람이 쓴 사유가 외부 LLM으로 나간다는 점을 먼저 정해야 한다(`docs/security.md`). 지금 L2 워커는 사유를 자기 연결로 읽어 `task.data` 안에만 넣는다.
- 반려 사유 전달 규칙은 `incident_artifacts`와 `incident_reviews.analysis_round`의 비교다. 실패한 재분석(Artifact 없음)에서는 `analysis_round`만 올라도 사유가 유지된다. 이 규칙을 바꿀 때는 `tests/test_l2_branch_db.py`의 `test_rejection_survives_failed_retries_but_not_a_newer_artifact`를 같이 본다.
- 이미 처리된 Incident(옛 데이터)는 `reviews`가 비어 있고 `review_round`는 옛 값이다. 소급 채움은 하지 않았다.
- 이 기록이 `365-pen-screens.md`의 "반려는 `review_round`를 올리지 않는다·사유 없음"과 `384-incident-detail-design.md`의 "반려·승인 이벤트 노드 없음"을 대체한다. 그 파일들은 고치지 않았다.
- `frontend/src/api/generated/IncidentDetail.ts`는 `pnpm contracts`로 갱신한 생성 파일이고 `reviews`가 선택 필드(`reviews?`)다. 화면은 없을 때를 빈 목록으로 본다.
- 반려 확인 창은 `design/`에 프레임이 없어 현재 스타일(`.review-dialog`)로 만들었다. PR에 "디자인 없음"으로 표시한다.
- 로컬에서 DB 테스트를 돌릴 때 `DATABASE_URL`의 DB가 없으면 임시 DB를 만들지 못한다. `postgres` 같은 기존 DB 이름을 가리키게 한다. `localhost`가 IPv6로 풀려 연결이 안 되면 `127.0.0.1`을 쓴다.
- L2 담당 승인(쓰기 API, 새 테이블, `IncidentDetail` 응답 변경, `review_round` 의미 변경)은 PR 전에 받아야 한다. 아직 받지 않았다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2711 통과.
- `uv run pytest -m db`: 716 통과, 2 실패. 실패 둘은 `QDRANT_URL`이 없어 나는 기존 실패다(`test_branch_reindex_detects_missing_point_and_recovers`, `test_vector_candidate_uses_current_incident_and_rejects_stale_payload`). 변경을 되돌려도 같게 실패한다. CI는 qdrant 서비스가 있다.
- `frontend/`에서 `pnpm contracts:check`, `pnpm lint`(경고 1건은 기존 `flow-chart.tsx`), `pnpm test`(210 통과), `pnpm build`: 통과. `pnpm test`가 DB 테스트와 동시에 돌 때 한 번 실패했고 단독으로 다시 돌린 세 번은 모두 통과했다.
- 주요 테스트: `tests/test_api_review.py`(사유 검증·검토 행·여러 번 반려·409에서 행 없음·동시 요청), `tests/test_incident_reviews_db.py`(제약, 에이전트 읽기 권한 없음), `tests/test_l2_branch_db.py`의 `*rejection*`·`test_worker_gives_the_reason_to_investigation_as_data_not_as_instructions`, `tests/test_l2_analyze.py`(프롬프트), `frontend/src/review.test.tsx`(확인 창), `frontend/src/incident-page.test.tsx`(이벤트 배치).
- 손으로 확인한 화면(스크린샷)은 하지 않았다. 반려 흐름 전·후 스크린샷은 사람이 PR에 붙인다(D-075).
