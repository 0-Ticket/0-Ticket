# 화면용 API

웹 화면(`frontend/`)과 화면용 API(`src/soc/api/`) 사이의 약속이다. mock(D-022)과 실제 API가 모두 이 문서를 따른다. API 서버 도구는 D-027에서 정한다.

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

## 읽기

| 메서드 · 경로 | 쿼리 | 응답 | 쓰는 화면 |
|---|---|---|---|
| `GET /api/tickets` | `status`, `handling_type`, `min_priority` | 목록: C6 Ticket | F1 |
| `GET /api/tickets/{ticket_id}` | | 아래 "티켓 상세" | F2 |
| `GET /api/alerts/{alert_id}` | | C5 AlertRecord | F1, F2 |
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
| `GET /api/metrics` | `from`, `to` (epoch 밀리초) | 아래 "지표" | F1, F6 |

검토 대기함(F1)은 `GET /api/tickets?status=awaiting_human`이다.

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
  "steps": ["C8 AgentStep (subject_type=ticket)"],
  "reviews": ["C9 HumanReview"],
  "incident_ids": ["이 티켓이 속한 Incident ID"]
}
```

판정(C7)은 `ticket.verdict`에 들어 있다.

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
| tickets_total | int | 기간 안에 만들어진 티켓 수 |
| tickets_awaiting_human | int | 지금 검토 대기 중인 티켓 수 |
| l1_reviews_total | int | 기간 안의 C9 수 |
| l1_overturned | int | 그중 `overturned`가 `true`인 수 (v1 박스 16. v2 정리는 후속) |
| l2_reviews_total | int | 기간 안의 C15 수 |
| l2_rejects_by_type | dict[str, int] | `reject_type`별 반려 수 (박스 21) |
| incident_members_by_source | dict[str, int] | 묶음 항목 `source`(`l1`, `human_l1`, `l3`)별 수 (v1 Correlation 기준. v2 정리는 후속) |
| normalize_failures_by_reason | dict[str, int] | `reason`별 C12 수 (박스 4) |

## 쓰기

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
