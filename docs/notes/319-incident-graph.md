---
issue: 319
date: 2026-11-15
owner: Juhyeok0603
plan: 319-incident-graph.md
supersedes: [250-l2-ticket-incident.md, 267-l2-related-window.md]
---

# L2 분류와 분석 입력을 그래프 경로로 전환한다

## 한 일

- `ticket_branch` 벡터 후보 수집과 재색인 CLI를 제거하고, Alert/Hunt 엔티티 경로로 Incident 후보를 찾는 분류 로직을 넣었다. Event는 연결 경로에 사용하지 않고, 공개 IP 단독 경로는 제외한다. 경로 없음과 탐색 한도 도달을 다른 상태로 Ticket에 저장한다.
- 분류 결과의 경로/탐색 상태를 L2 분석 입력에 넣고 `related` 주변 기록 수집을 제거했다. Incident 상세 API와 UI에 Ticket별 경로 노드, 연결선, 탐색 상태를 노출했다.
- D-027과 L2 분류 프롬프트를 갱신했고 D-053 `ticket_verdicts` 유사 사례 경로는 남겨둡다. 유사 사례 검색 설정이 없을 때 파이프 그래프 분류 준비 검사가 Qdrant를 요구하지 않게 조정했다.
- 그래프 fixture와 단위/기존 DB 통합 테스트 수정을 더했다. 파이프 DB 통합 테스트는 삭제된 벡터 테스트 도우미를 사용하지 않도록 갱신했다.
- CI DB 검증 후 랩 fixture에서 Alert들은 공유 Entity가 없어 각각 새 Incident로 분류되는 것이 맞음을 확인했다. 그 기대에 맞게 랩 사이클 통합 테스트를 바꾸고, API seed 테스트가 조회하는 Incident와 수정하는 Ticket이 같은 픽스처에서 오도록 수정했다. 현재 로컬에 `DATABASE_URL`이 없어 수정 후 DB 테스트는 재실행하지 못했다.

## 계획과 달라진 점

- 없음.

## 다음 사람이 알아야 할 것

- 분류 그래프 경로는 Ticket 상세 `details.l2_branch` 엔트리에 저장되며, 과거 Ticket에 대한 경로는 생성하지 않는다.
- 백엔드 엔티티 조회는 현재 엔티티 값의 표기를 비교한다. IPv6 축약 표기가 서로 다른 동일 주소는 DB에 붙지 않을 수 있다.
- DB 테스트는 `db` 마커와 임시 DB용 `DATABASE_URL`이 필요하다. 현 세션에서는 설정되지 않아 실행하지 못했다.

## 확인 방법

- 통과: `uv run ruff format .`(변경 없음), `uv run ruff check .`, 관련 파이썬 단위 테스트 62개, `pnpm contracts:check`, 프론트엔드 테스트 80개, `pnpm build`, 수정 UI 파일 Prettier/ESLint.
- 미통과/미확인: 전체 `uv run pytest`는 Windows에서 파일명에 개행 문자를 붙이는 `test_name_ending_in_newline_is_not_a_migration`이 `OSError` 로 실패하고, 이어진 접속 오류 테스트 대기 중 중단했다. 전체 `pnpm lint`는 수정하지 않은 32개 프론트 파일에서 Prettier 체크가 실패했다. 프론트 ESLint는 오류 없이 경고 1건이다. `db` 테스트는 `DATABASE_URL` 부재로 실행하지 못했다.
