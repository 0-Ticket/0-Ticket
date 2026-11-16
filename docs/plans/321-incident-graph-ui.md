---
issue: 321
date: 2026-11-16
owner: Juhyeok0603
supersedes: []
---

# Incident 상세에 엔티티 연결 관계도 표시

## 목표

Incident 상세에서 현재 소속 Ticket들이 Alert/Hunt와 공유 엔티티를 통해 어떻게 연결되는지 하나의 노드·연결선 관계도로 보여준다. 현재 소속, 저장된 후보 탐색 경로, 각 Ticket의 분류 당시 탐색 상태를 구분해 분석가가 관계와 한계를 함께 읽을 수 있게 한다.

## 방법

### 데이터와 의미

- 기존 `GET /api/incidents/{id}` 응답의 `incident.ticket_ids`를 현재 소속의 기준으로 삼고, `ticket_graphs`의 노드·연결선·탐색 상태를 읽는다. DB, API 계약, 분류·분석 로직은 바꾸지 않는다.
- `ticket_graphs[].ticket_id`는 경로를 탐색한 출발 Ticket이고, `GraphPath.ticket_id`는 경로 끝의 상대 Ticket이다. 각 `paths`에서 `path.incident_id === incident.id`인 것만 현재 Incident로 이어지는 저장 경로로 모은다. 다른 후보 Incident로 향한 경로는 그리지 않는다.
- 같은 `(kind, id)` 노드와 같은 시작·끝·종류의 연결선을 각각 하나로 합친다. Entity에는 백엔드가 준 정규화된 노드 ID를 사용한다. 연결선의 끝 노드가 해당 경로에 없으면 그 선은 그리지 않는다.
- Incident와 모든 소속 Ticket을 먼저 표시한다. `incident.ticket_ids`에서 만든 소속선과 저장 경로의 공유 엔티티 연결선을 구분하며, 경로의 `belongs_to` 선을 추가 근거선으로 중복 표시하지 않는다. 자기 분류 기록에 경로가 없는 Ticket도 후속 Ticket의 경로에서 상대 노드가 될 수 있으므로 그 후속 경로의 연결선은 남긴다.

### 화면

- Incident 제목 또는 ID, 상태, Ticket 건수를 관계도 위에 표시한다. Ticket·Alert/Hunt·Entity·Incident 노드는 종류와 식별값을 텍스트로 보여준다. 긴 값은 화면에서 줄바꿈하고 텍스트 설명에는 전체 값을 담는다.
- 소속선은 중립색, 저장된 공유 엔티티 연결선은 강조색으로 그리고 범례를 둔다. 화살표는 쓰지 않는다. 선이 공격의 시간 순서나 에이전트가 최종 선택에 사용한 특정 경로를 뜻하지 않는다고 안내한다.
- Incident, Ticket, Alert/Hunt, 공유 Entity를 일정한 층에 배치한다. Ticket과 그 Alert/Hunt를 같은 열에 두고, 공유 Entity를 연결된 기록 아래에 둔다. ID 기반의 안정적인 순서와 노드 너비·간격으로 좌표를 계산하고, 노드 아래 SVG에 선을 그린다. 큰 관계도는 패널 안에서 가로로 스크롤하며 이동 안내를 표시한다.
- 관계도 바로 뒤에 표시된 경로마다 출발 Ticket → Alert/Hunt → 엔티티 종류·값 → 상대 Alert/Hunt → 상대 Ticket 순서의 텍스트 설명을 둔다. 관계도에는 키보드 초점과 스크롤을 제공하고, SVG 선은 보조기기에 중복 낭독하지 않는다.
- 모든 소속 Ticket의 **분류 당시** 탐색 상태를 별도로 표시한다. `no_path`는 당시 후보 없음, `public_ip_only`는 공용 IP만 일치해 제외, `candidate_limit`는 후보 한도로 미완료, `legacy`는 과거 경로 기록 없음, `unknown`은 확인 불가로 적는다. 현재 Incident에 일치하는 저장 경로가 없거나 `ticket_graphs`가 누락돼도 Ticket 소속 자체는 표시한다. 혼합 상태를 감추는 전체 탐색 완료 표시는 두지 않는다.
- 노드 값과 경로 설명은 React 텍스트로만 렌더링한다. 기존 상세 링크의 ID 형식 검사와 권한 검사를 유지하고, 상세 패널의 로딩·오류·재시도 동작을 보존한다.

## 바꿀 곳

- `frontend/src/App.tsx`: Ticket별 가로 경로 목록을 Incident 단위 관계도로 바꾸고 Incident 문맥을 전달한다.
- `frontend/src/incident-graph.tsx`: 현재 Incident의 경로를 한 번 합쳐 SVG 선, HTML 노드, 탐색 상태, 텍스트 설명을 같은 데이터에서 그린다.
- `frontend/src/style.css`: 상세 패널 안의 노드·선·스크롤·범례 스타일을 더한다.
- `tests/fixtures/frontend/incident_graph.json`, `frontend/src/App.test.tsx`와 관계도 테스트: 손으로 만든 응답 샘플과 화면 동작 검증을 더한다.

## 다른 코드와 맞물리는 곳

- `GET /api/incidents/{id}`와 생성 TypeScript 타입의 기존 필드만 읽는다. 다른 코드가 사용하는 API 응답·함수·설정·DB 스키마는 바꾸지 않는다.
- `DetailPanel`의 기본 폭은 650px, 최소 폭은 360px이며 사용자가 조절할 수 있다. 관계도는 패널 안에서 스크롤한다.
- 기존 `internalLink`와 `useCan`의 ID·권한 검사를 우회하지 않는다. #319의 과거 경로 미소급 원칙을 유지한다.

## 범위 밖

- Incident 자동 병합·Ticket 재배정·분류 이유 추론, 과거 그래프 소급 생성.
- 새 API·DB 저장소·그래프 시각화 라이브러리·Pretext 제품 의존성.
- 그래프 편집, 노드 드래그, 물리 시뮬레이션, 확대·축소 설정, 공격 시간 순서 추론.
- GitHub에 직접 이슈 댓글·PR을 쓰거나 push·merge하는 일. 이 저장소의 금지 규칙에 따라 결과는 로컬 계획과 댓글 초안으로 남긴다.

## 완료 기준

- [ ] 손으로 만든 fixture에 서로 다른 출발·상대 Ticket ID, 실제 `GraphPath.edges`, 여러 경로가 공유하는 Entity, 다른 Incident 후보 경로, 분류 당시 경로가 없는 최초 Ticket을 담는다.
- [ ] 현재 Incident로 이어지는 경로만 선으로 표시되고 공유 Entity와 중복 연결선은 각각 하나로 합쳐진다. 최초 Ticket이 후속 경로의 상대가 될 때 연결선은 남고 당시 탐색 상태는 별도로 보인다.
- [ ] 소속선과 저장 경로의 공유 엔티티 연결선이 범례·색·텍스트에서 구분된다. 각 경로의 텍스트 설명에 출발·상대 Ticket, Alert/Hunt, 엔티티 종류·전체 값이 나온다.
- [ ] `no_path`, `public_ip_only`, `candidate_limit`, `legacy`, `unknown`, 현재 Incident 경로 없음, 혼합 상태, `ticket_graphs` 누락을 빈 관계도와 혼동하지 않고 표시한다.
- [ ] 20개 이상 노드를 가진 반복 경로 샘플에서도 중복 제거와 크기 계산이 작동한다. 375·768·1440px 화면과 360·650px·넓은 패널 폭에서 노드 겹침 없이 스크롤하며 읽을 수 있다.
- [ ] 키보드로 관계도에 초점을 옮겨 스크롤하고 같은 연결을 텍스트로 읽을 수 있다. 악의적인 문자열은 문자 그대로 표시되고 권한 없는 상세 링크는 생기지 않는다.
- [ ] `pnpm --dir frontend lint`, `pnpm --dir frontend test`, `pnpm --dir frontend build`, `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`와 화면 검사가 통과한다.

## 토론으로 정한 것

- 2026-11-16: 현재 Incident로 이어지는 **저장된 후보 탐색 경로**를 표시하는 A안을 선택했다. 기존 API에는 에이전트가 최종 선택에 사용한 개별 경로 표시가 없으므로, 관계선이 최종 판단의 특정 근거나 공격 순서를 뜻한다고 주장하지 않는다.
- 이슈의 기본 표시 기준에 소속선과 저장 경로의 의미 구분, Ticket별 분류 당시 상태, 출발·상대 Ticket 구분, 큰 관계도와 텍스트 설명 검증을 더했다. 여러 Ticket의 관계를 실제 데이터 의미대로 읽고 좁은 화면에서도 확인하기 위해서다.

## 바뀐 점
