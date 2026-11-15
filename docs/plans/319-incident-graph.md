---
issue: 319
date: 2026-11-15
owner: Juhyeok0603
supersedes: [250-l2-ticket-incident.md, 267-l2-related-window.md]
---

# L2 분류·분석을 그래프 기반으로 전환

## 목표

L2가 Ticket을 Incident에 분류할 때 벡터 유사도와 주변 Alert·Event 수집 대신 Ticket, Alert, Entity의 연결 경로를 사용한다. 분석가가 Incident의 Ticket들이 어떤 엔티티 경로로 연결됐는지와 탐색 범위를 화면에서 확인할 수 있게 한다.

같은 연결 그래프와 탐색 상태를 L2 분석 입력으로 전달해, 분석이 실제로 확인한 연결 근거와 탐색 한계를 반영하게 한다.

## 방법

### 그래프 구성과 분류

- 기존 Alert 출처 Ticket은 `Ticket → Alert → Entity → Alert → Ticket` 관계를 따라 연결 후보를 찾는다. Event는 Ticket 연결 경로에 넣지 않는다.
- L3 출처 Ticket은 `Ticket → Hunt → Entity`에서 탐색을 시작하고, Hunt 엔티티와 연결되는 Alert·Ticket 경로를 찾는다.
- 같은 엔티티 경로로 도달한 Ticket이 속한 Incident를 후보로 만든다. 공개 IP만 겹치는 경로는 후보 연결 근거에서 제외한다. 공개 여부는 표준 라이브러리 `ipaddress`의 전역 라우팅 가능 여부로 판별한다.
- 기존 `candidate_window_ms`와 `max_candidates`를 탐색 제한으로 재사용한다. 그래프를 끝까지 확인하기 전에 한도에 걸린 경우 탐색 상태를 미완료로 기록하고 새 Incident를 만든다. 제한 안에서 경로가 없음을 확인한 경우도 새 Incident를 만든다.
- 탐색이 완료되어 유효한 Incident 후보 경로가 있으면 현재 분류 에이전트가 그래프와 경로를 보고 기존 Incident 중 하나를 선택하거나 새 Incident를 선택한다. 출력 계약 검증과 Ticket·Incident 잠금, 상태 재확인 및 저장 트랜잭션은 기존 안전 절차를 유지한다.
- 분류 에이전트 실패, 출력 계약 오류, 존재하지 않거나 후보가 아닌 Incident 선택은 기존 Incident에 연결하지 않고 새 Incident로 처리한다.
- 경로, 연결 관계, 탐색 완료 여부와 한도 도달 여부를 Ticket의 기존 `details.l2_branch` 분류 상세에 저장한다. 신규 그래프 저장소는 만들지 않는다.

### L2 분석 입력

- Incident에 연결된 Ticket들의 저장 그래프 경로와 탐색 상태를 분석 문맥에 포함한다.
- 기존 `related` 주변 Alert·Event 일괄 수집은 기본 분석 입력에서 제거한다. 에이전트는 필요할 때 기존 읽기 전용 조회 도구로 그래프 밖의 기록을 가져올 수 있다.
- 분류 단계의 새 Incident 결정은 분석 보류·재시도 정책(D-028)을 바꾸지 않는다.

### API와 화면

- Incident 상세 API가 연결 Ticket들의 그래프 경로와 탐색 상태를 모아 응답한다.
- Incident 화면은 Ticket·Alert·Entity 노드와 관계 경로를 표시하고, 탐색 완료와 한도 도달 상태를 구분한다. 모델 출력과 로그 문자열은 기존 보안 규칙에 따라 텍스트로만 표시한다.
- API 모델·계약·생성된 TypeScript 타입을 프로젝트의 기존 생성 절차로 갱신한다.

### 기존 분류 색인

- L2 분류의 `ticket_branch` 벡터 색인, 임베딩 및 관련 재색인 경로는 새 그래프 분류에 더 이상 쓰지 않으므로 제거한다.
- 유사 사례 검색의 `ticket_verdicts` 컬렉션과 D-053 동작은 유지한다.
- 데이터베이스에 저장된 기존 Incident·Ticket 관계는 변경하지 않는다. 과거 분류 결과의 그래프 경로를 소급 생성하지 않는다.

## 바꿀 곳

- `src/soc/l2/branch/`: 후보 수집과 분류 문맥을 그래프 경로 기반으로 변경하고 기존 `ticket_branch` 검색·색인 경로를 제거한다.
- `src/soc/l2/analyze/context.py`, `src/soc/l2/prompts/l2_investigate.md`: 주변 `related` 입력을 제거하고 저장된 그래프·탐색 상태를 분석 입력으로 전달한다.
- `src/soc/api/routes/workflow.py`, `src/soc/api/ui_models.py`, `contracts/`, `src/soc/contracts/generated/`: Incident 상세 그래프 응답 계약을 연결한다.
- `frontend/src/App.tsx`, `frontend/src/api/generated/`: Incident 상세에 연결 경로 및 탐색 상태를 표시한다.
- `src/soc/db/migrations/`, `config/default.toml`, 관련 테스트·fixture: 필요한 저장/설정 변경, 테스트와 손으로 만든 샘플을 반영한다. 불필요한 마이그레이션과 설정 키는 추가하지 않는다.
- `docs/decisions.md`: D-027을 그래프 기반 분류로 갱신한다.

## 다른 코드와 맞물리는 곳

- Ticket의 `details.l2_branch`를 기록하고 Incident API가 Ticket별 그래프 데이터를 모은다. Ticket/Incident 기본 스키마 변경은 가능한 한 피하되, 응답 계약 변경은 `contracts/`와 생성 코드를 함께 갱신한다.
- D-027을 대체한다. L2 분류용 `ticket_branch`는 제거하고, D-053의 `ticket_verdicts`는 유지한다.
- L2 분석 문맥에서 `related`가 사라지므로 관련 프롬프트·근거 ID 추적·테스트를 함께 바꾼다. 조회 도구와 D-028 분석 실패 처리는 유지한다.
- 화면에 그래프 경로를 추가하며 새 시각화 라이브러리는 도입하지 않는다.

## 범위 밖

- Event를 통한 Ticket 연결, 공용 IP 단독 연결, 그래프 밖 기록의 기본 분석 입력 포함.
- Incident 자동 병합, 기존 Ticket 자동 재배정, 과거 분류 데이터의 그래프 소급 생성.
- 분석 실패에 대한 보류·재시도 정책 변경.
- 새로운 그래프 데이터베이스 또는 UI 의존성 도입.

## 완료 기준

- [ ] Fixture로 Alert 출처 Ticket의 엔티티 연결, L3 Hunt 엔티티 연결, Event 미사용, 공개 IP 단독 경로 제외를 검증한다.
- [ ] 탐색 한도 안에서 경로 없음과 탐색 한도 도달을 구분하고, 둘 다 새 Incident로 저장한다.
- [ ] 유효 경로가 있는 기존 Incident 후보 선택과 새 Incident 선택을 검증한다.
- [ ] Ticket별 그래프 경로·탐색 상태가 저장되고 Incident 상세 API가 이를 반환한다.
- [ ] L2 분석 입력에 같은 그래프·탐색 상태가 포함되고 `related` 주변 기록 묶음은 기본 입력에서 제외된다.
- [ ] Incident 화면에서 Ticket·Alert·Entity 경로와 탐색 완료·미완료 상태를 확인할 수 있다.
- [ ] L2 분류의 `ticket_branch` 코드·설정·색인 복구 경로가 제거되고 `ticket_verdicts` 유사 사례 검색은 유지된다.
- [ ] 동시 처리·재시도에서 Ticket이 중복 저장되거나 잘못된 Incident에 연결되지 않는다.
- [ ] 계약 생성 검사, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, 프론트엔드 검사(`pnpm lint`, `pnpm test`, `pnpm build`)가 통과한다.

## 토론으로 정한 것

1. L3 Ticket은 Hunt 엔티티에서 그래프 탐색을 시작한다. Alert가 직접 없는 출처도 그래프 분류 흐름에 포함하기 위해서다.
2. 공개 IP 단독 겹침은 기존 Incident 연결 근거로 쓰지 않는다. 공개 여부는 표준 라이브러리 `ipaddress`의 전역 라우팅 가능 여부로 판별하고, 다른 엔티티 경로는 후보로 인정한다.
3. 기존 `candidate_window_ms`, `max_candidates`를 탐색 제한으로 재사용한다. 제한 안에 경로를 확인하지 못하면 상태를 미완료로 기록하고 새 Incident를 만든다.
4. 그래프 경로와 탐색 상태는 Ticket의 `details.l2_branch`에 저장하고 Incident 상세 API가 모아 제공한다. 그래프 저장소를 추가하지 않는다.
5. 그래프를 L2 분석의 기본 입력으로 사용하고 `related` 일괄 수집은 제거한다. 필요 자료는 기존 조회 도구를 통해 가져온다.
6. 분류 단계는 기존 Incident 또는 새 Incident로만 결정한다. 분석의 D-028 실패 보류·재시도 동작은 유지한다.
7. L2 전용 `ticket_branch`는 제거하지만 `ticket_verdicts`는 유사 사례 검색용으로 유지한다. 과거 데이터의 그래프 경로 생성과 Incident 재분류는 하지 않는다.

## 바뀐 점
