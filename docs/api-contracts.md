# 화면용 API

웹 화면(`frontend/`)과 화면용 API(`src/soc/api/`) 사이의 약속이다. mock(D-022)과 실제 API가 모두 이 문서를 따른다. API 서버는 FastAPI다(D-027).

## 원칙

- **응답은 계약 객체 그대로다.** 객체의 필드명, 타입, 선택 여부는 `docs/data-contracts.md`를 따른다. 이 문서는 어떤 객체를 어떤 묶음으로 돌려주는지만 정한다.
- **새 필드를 만들지 않는다.** 화면에 필요한 값이 계약에 없으면 계약 변경 절차(`docs/data-contracts.md` "바꾸는 절차")를 밟는다. 예외는 아래 "지표" 하나다.
- **검증은 코어가 한다.** API는 받은 검토 입력을 코어로 넘기고, 코어의 검증 결과를 그대로 돌려준다.
- **읽기 위주다.** 쓰기는 사람의 검토 입력과 Case 작업 수정뿐이다. 대응을 실행하는 API는 만들지 않는다.

## 공통

- 주소는 `/api`로 시작한다. 요청과 응답 본문은 JSON이다.
- 시간은 epoch 밀리초 정수, 필드명은 `snake_case`다(계약 공통 규칙).
- 목록 응답은 아래 모양이다. `next_cursor`가 `null`이면 마지막 쪽이다.

  ```json
  { "items": [], "next_cursor": null }
  ```

- 목록 요청은 `cursor`, `limit`(기본 50, 최대 200)을 받는다.
- 오류 응답은 아래 모양이다. `code`는 `not_found`, `invalid_input`, `conflict`, `internal` 중 하나다.

  ```json
  { "error": { "code": "invalid_input", "message": "reason is required when overturning" } }
  ```

- `code`마다 HTTP 상태 코드가 하나다. 쿼리·경로 값이 형식에 맞지 않는 경우도 서버 기본 형식(422)이
  아니라 아래 `invalid_input`으로 돌려준다. mock도 같은 상태 코드를 쓴다.

  | code | 상태 | 쓰는 때 |
  |---|---|---|
  | `invalid_input` | 400 | 필터·`cursor`·`limit` 값이 잘못됐거나 본문 검증에 걸림 |
  | `not_found` | 404 | 경로가 가리키는 대상이 없음 |
  | `conflict` | 409 | 이미 처리된 대상에 쓰기를 보냄 |
  | `internal` | 500 | 그 밖의 오류. `message`에 예외 원문이나 로그 원문을 넣지 않는다 |

## 읽기

| 메서드 · 경로 | 쿼리 | 응답 | 쓰는 화면 |
|---|---|---|---|
| `GET /api/tickets` | `status`, `origin`, `handling_type`, `min_priority` | 목록: C6 Ticket | F1 |
| `GET /api/tickets/{ticket_id}` | | 아래 "티켓 상세" | F2 |
| `GET /api/alerts/{alert_id}` | | C5 AlertRecord | F1, F2 |
| `GET /api/alerts/{alert_id}/l1` | | 아래 "알럿 L1 상세" | F1, F2 |
| `GET /api/l1/decisions` | `subject_type`, `decision`, `reason` | 목록: C23 L1DecisionRecord | F1 |
| `GET /api/events/{event_id}` | | C13 EventRecord | F2, F5 |
| `GET /api/raw/{raw_id}` | | C1 RawRecord | F2 |
| `GET /api/incidents` | `status`, `created_by` | 목록: C10 Incident | F3 |
| `GET /api/incidents/{incident_id}` | | 아래 "Incident 상세" | F3 |
| `GET /api/cases` | `status` | 목록: C16 Case | F4 |
| `GET /api/cases/{case_id}` | | 아래 "Case 상세" | F4 |
| `GET /api/hunts` | `is_anomaly` | 목록: C17 HuntFinding | F5 |
| `GET /api/hunts/{hunt_id}` | | 아래 "헌팅 상세" | F5 |
| `GET /api/rules` | `status` | 목록: C18 RuleProposal | F5 |
| `GET /api/rules/{proposal_id}` | | C18 RuleProposal | F5 |
| `GET /api/normalize-failures` | `reason` | 목록: C12 NormalizeFailure | 현재 없음. API와 응답은 그대로이며, F6은 C12 목록 대신 지표의 `normalize_failures_by_reason`을 표시한다(#31) |
| `GET /api/metrics` | `from`, `to` (epoch 밀리초) | 아래 "지표" | F6 |

검토 대기함(F1)은 `GET /api/tickets?status=awaiting_human`이다. v2 L1은 `awaiting_human`
티켓을 새로 만들지 않는다(`docs/data-contracts.md` C6).

**지금 구현된 경로** (번호 없는 L1 결과 조회, #71): `GET /api/tickets`, `GET /api/tickets/{ticket_id}`,
`GET /api/alerts/{alert_id}`, `GET /api/alerts/{alert_id}/l1`, `GET /api/l1/decisions`,
`GET /api/metrics`(#103, 집계 없이 `available: false`만 돌려준다).
나머지 읽기 경로(`/api/events`, `/api/raw`, `/api/incidents`, `/api/cases`, `/api/hunts`,
`/api/rules`, `/api/normalize-failures`)는 해당 박스가 L1 범위 밖이라
**현재 미구현(발표 후 구현 예정)**이다. 경로와 응답 모양은 이 문서에 그대로 두고 mock도 그대로 쓴다.

`GET /api/tickets`의 필터(`status`, `origin`, `handling_type`, `min_priority`)는 페이지를 나누기
전에 적용한다. `min_priority`는 `priority`가 그 값 이상인 티켓만 남기는 정수이고, 0 이상이 아니거나
정수가 아니면 `invalid_input`이다. `handling_type`은 등록형 값이라 정해진 목록으로 막지 않고 받은
문자열로 비교한다(빈 문자열은 `invalid_input`). 받은 페이지에서 걸러 내는 방식은 쓰지 않는다. 그래야
페이지별 누락과 빈 페이지가 생기지 않는다.

`GET /api/tickets`는 필터 적용 후 다음 순서를 보장한다. 커서 페이지를 나누기 전에
이 순서를 적용하며, 같은 데이터 집합을 순회할 때 페이지 사이에 중복·누락이 없어야 한다.

1. `priority` 내림차순
2. 같은 priority에서는 `created_at` 오름차순
3. 두 값도 같으면 `ticket_id` 오름차순 (문자열 순서)

화면은 응답 순서를 그대로 유지하고 `next_cursor`로 다음 페이지를 요청한다.
새 sort 매개변수는 추가하지 않는다. 정렬 보장은 변경 중인 데이터의 스냅샷 보장을 뜻하지 않는다.


### 티켓 상세

```json
{
  "ticket": "C6 Ticket",
  "alerts": ["C5 AlertRecord"],
  "findings": ["C14 SpecialistFinding"],
  "decisions": ["C23 L1DecisionRecord (subject_type=ticket)"],
  "evidence_requests": ["C22 EvidenceRequest (requester_type=ticket)"],
  "steps": ["C8 AgentStep (ticket 단계 + alert_ids의 alert 단계)"],
  "reviews": ["C9 HumanReview"],
  "incident_ids": ["이 티켓이 속한 Incident ID"]
}
```

판정(C7)은 `ticket.verdict`에 들어 있다.

- `alerts`: `ticket.alert_ids` 순서대로 담는다. 저장소에 없는 `alert_id`는 `alerts`에서 빠지고
  `ticket.alert_ids`에는 남는다(500이 아니다). 화면은 남은 ID를 그대로 보여 준다.
- `findings`: `status`가 `completed`인 `specialist_agent` 요청의 `result.finding`이다. 그런 요청이
  없으면 `[]`.
- `decisions`: 이 티켓이 주체인 C23만, 새것부터. 연결된 알럿의 C23은 "알럿 L1 상세"에서 본다.
- `evidence_requests`: 이 티켓이 요청자인 C22 전체를 들어온 순서대로. `failed` 요청의
  `failure_reason`이 증거 수집 실패 표시다(번호 없는 증거 요청 큐, D-034).
- `steps`: 티켓 단계와 `alert_ids`가 가리키는 알럿 단계를 합쳐 `created_at` 순으로 돌려준다(#44).
  C8 필드만 담고, 큰 결과의 보관 파일 경로·해시는 내보내지 않는다.
- `reviews`와 `incident_ids`: v2 L1에서는 항상 `[]`다. 사람이 L1 판정을 검토하지 않고(v1 박스 16 폐기),
  Incident 묶음은 L2의 23~29 범위다.

### 알럿 L1 상세

보류돼 티켓이 없는 알럿은 여기서 L1 결과를 본다.

```json
{
  "alert": "C5 AlertRecord",
  "branch": "C21 BranchResult 또는 null",
  "decisions": ["C23 L1DecisionRecord (subject_type=alert)"],
  "evidence_requests": ["C22 EvidenceRequest (requester_type=alert)"],
  "steps": ["C8 AgentStep (subject_type=alert)"]
}
```

- 알럿이 없으면 `not_found`다. 알럿은 있는데 아직 분기(C21)나 판정(C23)이 없으면 `branch`는 `null`,
  목록은 `[]`이고 응답은 200이다.
- `decisions`는 이 알럿이 주체인 C23만, 새것부터 담는다. `steps`는 티켓 상세와 같은 규칙이다.

### Incident 상세

```json
{
  "incident": "C10 Incident",
  "tickets": ["C6 Ticket (member_type이 ticket인 항목)"],
  "hunts": ["C17 HuntFinding (member_type이 hunt인 항목)"],
  "artifact": "C11 IncidentArtifact 또는 null",
  "steps": ["C8 AgentStep (subject_type=incident)"],
  "reviews": ["C15 L2Review"],
  "case_id": "만들어진 Case ID 또는 null"
}
```

### 헌팅 상세

```json
{
  "hunt": "C17 HuntFinding",
  "steps": ["C8 AgentStep (subject_type=hunt)"],
  "proposal_ids": ["이 헌팅에서 나온 룰 제안 ID"]
}
```

### Case 상세

```json
{
  "case": "C16 Case",
  "proposal_ids": ["이 Case에서 나온 룰 제안 ID"]
}
```

### 지표

계약 객체가 아닌 유일한 응답이다. 화면용 집계라서 이 문서에서 정의한다. 필드를 바꾸려면 계약과 같은 절차를 밟는다.

| 필드 | 타입 | 설명 |
|---|---|---|
| from | int | 집계 시작 |
| to | int | 집계 끝 |
| available | bool | 집계 결과가 있는지. `false`면 아래 지표 여덟 개를 담지 않는다 |
| tickets_total | int | 기간 안에 만들어진 티켓 수 |
| tickets_awaiting_human | int | 지금 검토 대기 중인 티켓 수 |
| l1_reviews_total | int | 기간 안의 C9 수 |
| l1_overturned | int | 그중 `overturned`가 `true`인 수 (v1 박스 16. v2 정리는 후속) |
| l2_reviews_total | int | 기간 안의 C15 수 |
| l2_rejects_by_type | dict[str, int] | `reject_type`별 반려 수 (36 Human) |
| incident_members_by_source | dict[str, int] | 묶음 항목 `source`(`l1`, `human_l1`, `l3`)별 수 (v1 Correlation 기준. v2 정리는 후속) |
| normalize_failures_by_reason | dict[str, int] | `reason`별 C12 수 (6 OCSF) |

`available`로 두 가지 응답을 가른다. 둘 다 200이다. 집계할 것이 없다는 사실은 오류가 아니다.

- `available: false`: `from`, `to`, `available` 세 필드만 담는다. 지표 여덟 개는 **넣지 않는다**.
  0을 채우면 "세어 봤더니 없음"과 구분되지 않기 때문이다(#103).
- `available: true`: 위 표의 열한 필드를 모두 담는다.

`from`과 `to`는 정수여야 하고 `from`이 `to`보다 크면 `invalid_input`이다.

## 쓰기

**발표 후, L1 결과에는 쓰지 않음.** 아래 쓰기 경로는 모두 L2·Case·룰 단계(34, 36, 37)의 것이고
**현재 미구현(발표 후 구현 예정)**이다. L1 결과(승격·보류·판정)를 바꾸는 경로는 앞으로도 만들지 않는다.
사람의 승인은 36에만 있다(`docs/architecture.md`). `POST /api/tickets/{ticket_id}/reviews`는
폐기된 v1 박스 16의 경로이며 v2 L1 결과에는 쓰지 않는다.

| 메서드 · 경로 | 요청 본문 | 응답 | 쓰는 화면 |
|---|---|---|---|
| `POST /api/tickets/{ticket_id}/reviews` | `reviewer`, `decision` (`tp`, `fp`), `reason` | C9 HumanReview | F2 |
| `POST /api/incidents/{incident_id}/reviews` | `reviewer`, `decision` (`approve`, `reject`), `reject_type`, `comment`, `expected_review_round` | C15 L2Review | F3 |
| `POST /api/rules/{proposal_id}/reviews` | `reviewer`, `decision` (`approve`, `reject`) | C18 RuleProposal | F5 |
| `PATCH /api/cases/{case_id}` | `status`, `tasks`, `lessons` 중 바꿀 것만 | C16 Case | F4 |

- 요청 본문의 선택 값은 보내지 않아도 된다. 계약 객체의 필드명을 그대로 쓴다.
- `overturned`(C9)와 `round`(C15)는 보내지 않는다. 코어가 정한다.
- `expected_review_round`는 L2 검토 요청에서 필수다. 아래 "L2 검토 기회 (#21)" 참고.
- 코어 검증에 걸리면 `invalid_input`을 돌려준다. 예: 판정을 뒤집으면서 `reason`이 없음, 반려하면서 `reject_type`이 없음
- 이미 처리된 대상(예: 검토가 끝난 티켓)에 다시 보내면 `conflict`를 돌려준다.
- 룰 승인은 C18 `status`를 `approved`로 바꿀 뿐이다. SIEM 반영(`deployed`)은 화면 API가 하지 않는다.

## C6 Ticket 필드 추가 (#12)

`awaiting_human_at: int | null`은 Ticket 객체의 필수 필드로 전달된다.
`GET /api/tickets`의 `items`, `GET /api/tickets/{ticket_id}`의 `ticket`,
`GET /api/incidents/{incident_id}`의 `tickets`에 포함되는 Ticket이 영향 대상이다.
필드 의미는 `docs/data-contracts.md`의 C6을 따른다.

목록·상세의 응답 묶음 구조, 페이지 커서, 정렬, 지표 의미는 변경하지 않는다.
새 API나 검토 완료 시각·소요 시간 지표는 추가하지 않는다.

## L2 검토 기회 (#21)

C10 Incident에 `review_state`, `review_round`가 필수 필드로 추가됐다(의미는 `docs/data-contracts.md` C10 "L2 검토 흐름").
`GET /api/incidents`의 `items`와 `GET /api/incidents/{incident_id}`의 `incident`가 영향 대상이다.
응답 묶음 구조, 페이지 커서, 지표 의미는 바꾸지 않는다.

| 값 | 위치 | 역할 |
|---|---|---|
| `status` | C10 | Incident 생명주기. 검토 가능 여부를 판단하는 데 쓰지 않는다 |
| `review_state` | C10 | L2 검토 흐름. `awaiting_review`일 때만 검토를 받는다 |
| `review_round` | C10 | 지금 열려 있는 검토 기회 |
| `expected_review_round` | 요청 본문 | 요청이 답하는 기회. 사전 조건(낙관적 동시성) 값이며 저장하지 않는다 |
| `round` | C15 응답 | 코어가 기록한 실제 검토 회차 |

`POST /api/incidents/{incident_id}/reviews` 처리 순서:

1. Incident가 없으면 `not_found`
2. `review_state`가 `awaiting_review`가 아니면 `conflict` (승인됨, 재분석 중, 사람 직접 처리)
3. 본문 검증에 걸리면 `invalid_input`. `expected_review_round` 누락·정수 아님 포함
4. `expected_review_round`가 지금 C10 `review_round`와 다르면 `conflict` (예: 다른 탭이 이미 답했고 새 기회가 열림)
5. 통과하면 코어가 C15를 기록하고 `round`에 그 기회의 회차를 넣는다. 같은 기회에는 한 건만 기록되며, 동시에 온 요청 중 하나만 성공한다

이 순서는 의도한 것이다. 검토 기회가 닫혀 있으면 본문이 잘못돼도 `conflict`다. 그래야 화면이 다시 조회해 최신 상태를 보여 준다.
기회가 열려 있으면 본문 오류(`invalid_input`)를 회차 불일치(`conflict`)보다 먼저 알린다. 기존 C9 티켓 검토의 "이미 처리됨 → `conflict`, 그다음 본문 검증" 순서와 같다.

- 화면은 GET에서 받은 `review_round`를 계산 없이 `expected_review_round`로 보낸다. 클라이언트가 회차를 정하는 값이 아니다.
- 성공 후 `review_state`는 승인이면 `approved`, 첫 번째 반려면 `analyzing`, 두 번째 반려면 `human_handling`이 되고 `review_round`는 `null`이 된다. `status`는 바뀌지 않는다.
- 검토 채널 플러그인(`review_channels`)도 같은 규칙을 따른다.
