---
issue: 250
date: 2026-11-05
owner: Juhyeok0603
supersedes: []
---

# Ticket을 Incident로 분류하고 벡터 후보 색인하기

## 목표

`status = escalated`인 Ticket을 하나씩 받아 기존 Incident에 연결하거나 새 Incident를 만든다.

기본 후보 경로는 비슷한 Ticket을 찾는 `vector`다. 벡터 경로를 사용할 수 없거나 유효 후보가 없으면
시간 창 안의 열린 Incident를 최근 활동순으로 읽는 `recent` 경로를 사용한다. 엔티티 겹침과 신호
등급은 후보 검색과 순위에서 완전히 제거한다.

분류 결과를 PostgreSQL에 원자적으로 저장하고, 연결된 Ticket을 Qdrant 파생 색인에 적재한다. L2
워커를 `soc.agent` 실행기에 등록하고 PostgreSQL에서 색인을 복구하는 `reindex` 명령을 제공한다.

## 방법

### 선행 조건

- #257 벡터 저장소·임베더는 PR #259로 `main`에 머지됐다.
- #226의 Ticket 문맥 조회를 재사용하되 열린 Incident 전수 조회와 엔티티 신호 계산은 분리·삭제한다.
- #209의 `run_agent`·`AgentTask`, #210의 프롬프트 계층, #215의 실행기·`AgentWorker`를 그대로
  사용한다.
- 새 라이브러리와 DB 마이그레이션은 추가하지 않는다.

### Incident 분류 결정(D-027) 변경

D-027을 다음과 같이 고친다.

- 후보 경로는 `vector`와 `recent`다.
- `vector`는 비슷한 Ticket이 속한 Incident를 후보로 삼고 최고 Cosine 유사도로 순위를 매긴다.
- `recent`는 시간 창 안의 열린 Incident를 `updated_at` 내림차순으로 고른다.
- 엔티티 겹침으로 후보를 추리거나 순위를 매기지 않는다.
- 강한·보조·공용 엔티티 등급과 관련 설정을 삭제한다.
- 에이전트가 실패하거나 후보에 없는 Incident를 고르면 새 Incident를 만든다.
- 유사도만으로 기존 Incident에 자동 연결하지 않는다.

D-027 메모에는 다음을 기록한다.

- 엔티티 겹침을 제거하면 같은 해시·계정을 공유해도 Alert 서술이 달라 유사도가 낮은 Ticket을 묶지
  못할 수 있다.
- 에이전트 실패 시 새 Incident를 만드는 이유는 잘못 연결된 Ticket을 되돌릴 수단이 없기 때문이다.
- 실행 중 컬렉션이 같은 차원이지만 다른 거리 방식으로 재생성되면 다음 워커 재시작 전까지 감지하지
  못한다.
- 잘못 연결된 Ticket의 자동 재배정과 Incident 병합은 제공하지 않는다.
- 새 Incident로 떨어진 비율과 사유를 운영 실측으로 확인한다.

D-013과 D-031은 바꾸지 않는다.

### 설정

`[l2.branch]`는 아래 네 키만 받는다.

```toml
[l2.branch]
candidate_window_ms = 86_400_000
max_candidates = 5
candidate_source = "vector"
top_k = 50
```

- `candidate_window_ms`, `max_candidates`, `top_k`는 양의 정수다.
- `candidate_source`는 `vector | recent`다.
- 예상하지 않은 키를 거부한다.
- `strong_signal_types`, `weak_signal_types`, `shared_entity_values`와 엔티티 7종 불변식을 삭제한다.

`top_k=50`, `max_candidates=5`, `reasoning_effort="medium"`은 이번 이슈에서 바꾸지 않는다. 운영
실측은 후속 튜닝 이슈의 입력으로만 기록하며 이번 완료 기준에는 넣지 않는다.

### 워커 시작과 컬렉션 확인

`build_worker(config)`가 시작될 때 `VectorStore.ensure_collection()`을 한 번 호출한다.

- 컬렉션이 없으면 현재 임베더 차원과 Cosine으로 만든다.
- 컬렉션이 있으면 unnamed vector 하나인지, 차원과 거리 방식이 맞는지 확인한다.
- `CollectionMismatch`는 워커 생성 실패로 처리한다.
- 그 밖의 `StoreError`는 오류 종류만 경고하고 워커를 시작한다.
- Ticket마다 컬렉션 정보를 다시 확인하지 않는다.

환경변수 누락과 잘못된 주소는 `VectorStore.__init__()`의 `create_client()`에서 걸리므로 워커 생성
실패다. `ensure_collection()`의 일반 `StoreError`는 `exists()`, `get_collection()`,
`create_collection()` 등 Qdrant 연산 실패이며 접속 실패로만 한정하지 않는다. 일반 `StoreError`
뒤에도 워커를 시작하는 이유는 건별 `query_failed → recent` fallback을 유지하기 위해서다.

실행 중 컬렉션이 삭제되면 `search()`가 `CollectionMissing`을 내고 해당 Ticket은 `recent`로
진행한다. 커밋 뒤 upsert도 `CollectionMissing`이면 오류 종류만 기록하고 넘기며 `reindex`로
복구한다.

### #226 코드 정리

다음을 삭제한다.

- `src/soc/l2/branch/signals.py`
- `src/soc/l2/branch/candidates.py`
- 엔티티 등급·겹침 테스트

문맥 조회와 후보 조회를 분리한다.

Ticket 문맥 조회:

- 대상 Ticket을 읽고 상태를 확인한다.
- `alert_ids` 순서대로 Alert를 읽는다.
- L3 Ticket이면 `hunt_id`로 Hunt를 읽는다.
- Ticket·Hunt의 `alt_`, `evt_`, `agl_` 근거가 실제로 존재하는지 확인한다.
- 없는 근거는 제외하고 개수만 기록한다.
- 기존 계약 검증과 epoch 밀리초 변환을 유지한다.
- 열린 Incident를 조회하지 않는다.

후보 조회:

- `recent`용 열린 Incident 조회
- vector hit가 가리킨 Incident 일괄 조회
- 최종 후보 hit의 Ticket·대표 Alert·Hunt 일괄 조회
- Incident 상태·시간 창과 Ticket 소속 관계 확인

`BranchContext.signals`는 제거한다. Incident에 저장할 엔티티는 `Ticket.entities`만 사용한다. L3
Ticket은 생성 시 Hunt 엔티티를 이미 복사하므로 Hunt 엔티티를 다시 합치지 않는다.

### 임베딩 텍스트

순수 함수가 다음 값을 고정된 순서로 모아 줄바꿈으로 연결한다.

1. `alert_ids` 순서의 Alert `title`
2. 확인된 근거 순서의 Event `summary`
3. Ticket `verdict.reason`
4. L3 Ticket이면 Hunt `hypothesis`
5. L3 Ticket이면 Hunt `reason`

- 레이블을 붙이지 않는다.
- 빈 값은 넣지 않는다.
- 객체 전체와 `details`는 직렬화하지 않는다.
- 값은 지시가 아니라 임베딩 데이터로만 다룬다.
- 토큰 절단은 #257 임베더 tokenizer에 맡긴다.
- 입력 순서와 중복은 보존한다.

레이블을 넣지 않는 이유는 모든 Ticket에 같은 토큰이 들어가 Cosine 점수가 1 쪽으로 눌리는 것을
막고, 제목 하나뿐인 짧은 Ticket에서 레이블이 토큰의 큰 비중을 차지하지 않게 하며, Hunt 가설과
Alert 제목처럼 서로 다른 출처의 같은 공격 표현이 교차 매칭되게 하기 위해서다. 임베딩 텍스트는
Qdrant에만 사용하고 에이전트에는 구조화된 문맥을 별도로 제공한다.

합성 결과가 비면 임베딩과 Qdrant 검색을 하지 않고 `recent` 후보 경로를 사용한다.
`candidate_fallback = "empty_text"`를 기록하고 저장 뒤에도 색인하지 않는다. `reindex`에서는 오류가
아닌 정상적인 적재 생략으로 센다.

### vector 후보 검색

1. Ticket 임베딩 텍스트를 벡터로 만든다.
2. `ticket_branch` 컬렉션에서 비슷한 Ticket을 `top_k`개까지 찾는다.
3. point ID와 payload `incident_id`의 모양을 확인한다.
4. 모양이 잘못된 hit만 버리고 `invalid_hit_count`를 올린다.
5. 남은 hit가 가리킨 Incident를 PostgreSQL에서 한 번에 읽는다.
6. 열린 상태와 `updated_at` 시간 창을 통과한 Incident만 남긴다.
7. Incident별 최고 유사도와 그 점수를 만든 Ticket ID를 정한다.
8. 최고 유사도 내림차순으로 임시 상위 `max_candidates` Incident를 고른다.
9. 임시 후보에 속한 hit Ticket을 제목 조회와 함께 한 번에 읽고 PostgreSQL 관계를 확인한다.
10. 관계가 틀린 hit는 버리고 `invalid_hit_count`를 올린다.
11. Incident별 남은 hit 중 최고 유사도와 대표 Ticket을 다시 정한다.
12. 같은 최고 유사도 기준으로 최종 후보를 다시 정렬한다.
13. 관계 검사로 탈락한 후보 자리는 다음 순위 Incident로 채우지 않는다.
14. 최종 후보마다 대표 Ticket 제목을 붙인다.

관계 검사는 hit Ticket이 PostgreSQL에 존재하고 `linked`이며 payload Incident의 `ticket_ids`에 그
Ticket ID가 포함되는지 확인한다. 관계가 부정되면 비슷한 Ticket이 그 Incident에 속한다는 후보
선정 근거가 사라지므로 해당 hit를 사용하지 않는다. 열린 상태와 시간 창은 후보 필터일 뿐 소속
관계를 대신하지 않는다.

한 Incident의 최고 hit가 탈락해도 다른 유효 hit가 있으면 그중 최고 점수와 대표 Ticket으로 다시
계산한다. 남은 hit가 없으면 해당 Incident 후보를 제거한다. 관계 검사 전후의 두 정렬은 모두 같은
최고 유사도 기준을 사용하며, 서로 다른 기준을 섞어 순위를 다시 만드는 동작은 아니다.

탈락한 후보 자리를 다음 순위로 채우지 않는 이유는 새 후보의 Ticket 제목과 관계를 읽기 위한 추가
DB 조회를 피하기 위해서다. 따라서 최종 후보 수가 `max_candidates`보다 적을 수 있다. 최종 후보가
모두 제거되면 `no_valid_candidates → recent`로 진행한다.

point와 payload는 다음과 같다.

```text
컬렉션 목적: ticket_branch
point ID: Ticket ID에서 tkt_를 제거한 UUIDv7
vector: 합성한 임베딩 텍스트
payload: incident_id 하나
```

Ticket 시각과 제목은 payload에 넣지 않는다.

후보마다 에이전트에 Incident ID·제목, 소속 Ticket 수, `updated_at - created_at`으로 계산한 기간을
제공한다. vector 후보이면 최고 유사도와 최고 유사도 hit의 Ticket ID·제목도 제공한다. 대표 Ticket
제목은 대표 Alert 제목, L3 Hunt 가설 순으로 구하고 둘 다 없으면 비운다.

닫힌 Incident는 후보에서 제외하고 해당 `incident_id`를 payload로 가진 point를 모두 삭제한다.
시간 창 밖 Incident의 point는 삭제하지 않는다.

### recent 후보 조회

`candidate_source = "recent"`이거나 vector 경로가 fallback하면 다음과 같이 조회한다.

- `updated_at`이 시간 창 안인 Incident만 읽는다.
- 열린 상태는 `analyzing`, `awaiting_review`, `human_handling`이다.
- `updated_at` 내림차순으로 정렬한다.
- 상위 `max_candidates`개만 사용한다.
- 비슷한 Ticket ID·제목과 유사도는 제공하지 않는다.
- recent 결과가 0건이어도 vector 경로로 돌아가지 않는다.

### 후보 fallback 기록

`candidate_source`는 실제 최종 후보를 만든 경로인 `vector | recent`다.

| 값 | 의미 |
|---|---|
| `null` | 설정이 recent이거나 vector가 정상 후보를 만듦 |
| `empty_text` | 임베딩 텍스트가 없어 검색하지 않음 |
| `collection_missing` | 실행 중 컬렉션이 없어짐 |
| `query_failed` | Qdrant 검색 실패 |
| `no_valid_candidates` | 검색했지만 PostgreSQL 검증을 통과한 후보가 없음 |

모양 또는 관계가 잘못된 hit 일부를 버린 뒤에도 유효 후보가 남으면 vector 경로를 유지한다. 전부
버리거나 PostgreSQL 검증 뒤 후보가 없으면 `no_valid_candidates`로 recent에 떨어진다.
`CollectionMismatch`는 fallback하지 않는다. vector와 recent 결과가 모두 0건이면 에이전트를 부르지
않고 새 Incident를 만든다.

### 분류 출력 계약

`contracts/branch_decision.schema.json`을 만든다.

| 필드 | 규칙 |
|---|---|
| decision | new 또는 existing |
| `incident_id` | existing이면 `inc_` ID 모양, new이면 null |
| `confidence` | 0~1 |
| `reason` | 선택 이유 |
| `similar_ticket_ids` | 모델에게 보여 준 비슷한 Ticket ID의 중복 없는 부분집합 |

Draft-07 `if/then`으로 다음을 강제한다.

- `decision = new`이면 `incident_id = null`
- `decision = new`이면 `similar_ticket_ids.maxItems = 0`
- `decision = existing`이면 `incident_id`가 `inc_` 접두사와 UUIDv7 모양을 가져야 한다

계약은 Incident의 실제 존재 여부를 확인하지 않는다. 실제 존재와 이번 후보 목록 포함 여부는 코드가
검사한다. 계약을 `_CONTRACTS`에 `branch_decision`으로 등록하고 생성 코드를 갱신한다. 유효·무효
fixture와 계약 샘플 목록도 추가한다.

### 에이전트 호출

`AgentTask`는 다음 값으로 만든다.

```text
stage = l2
task = l2_classify
subject_type = ticket
subject_id = 대상 Ticket ID
output_contract = branch_decision
allowed_evidence_ids = ()
cited_ids = 빈 목록을 반환하는 함수
```

입력에는 Ticket의 구조화된 전체 분류 문맥, 후보 Incident 정보, 실제 후보 경로 `vector | recent`를
담는다.

4층 프롬프트는 `src/soc/l2/prompts/l2_classify.md`에 둔다. `contains_forbidden()`을 통과하고 1층
공통 지시를 반복하지 않으며, 추가 조회가 필요 없는 분류 작업임을 알리고 JSON 계약에 맞춰 new와
existing 중 하나를 고르게 한다.

2층 `src/soc/agent/prompts/l2.md`는 분류와 분석을 모두 포괄하도록 중립화한다. 이 변경으로
`prompt_version` 해시가 바뀐다. 운영에서는 기존 `[tools.allowed].l2` 도구가 그대로 등록된다.
작업별 도구 분리는 만들지 않는다.

### 에이전트 결과 검사

계약 검증 뒤 코드가 다음을 확인한다.

- existing의 `incident_id`가 이번에 보여 준 후보 목록에 있는가
- `similar_ticket_ids`가 이번에 보여 준 대표 Ticket ID의 부분집합인가

new의 빈 `similar_ticket_ids`는 계약이 검사한다.

다음 결과는 기존 Incident에 붙이지 않고 새 Incident를 만드는 규칙 fallback이다.

- `format_error`
- `evidence_id_error`
- `budget_exceeded`
- `rate_limited`
- `provider_error`
- `log_error`
- 후보에 없는 Incident
- `decision`과 `incident_id` 불일치
- `similar_ticket_ids` 부분집합 위반
- 저장 직전 선택한 Incident가 닫힘

`cancelled`는 저장하지 않는다. Ticket을 `escalated`로 남겨 재시작 뒤 다시 처리한다.

### Ticket 분류 기록

저장할 때 `Ticket.details.l2_branch`에 아래 다섯 칸을 항상 둔다.

```json
{
  "candidate_source": "vector",
  "candidate_fallback": null,
  "invalid_hit_count": 0,
  "decision_source": "agent",
  "decision_fallback": null
}
```

`invalid_hit_count`에는 point ID 또는 payload `incident_id` 모양이 잘못된 hit와, 최종 후보 검사에서
Ticket이 없거나 linked가 아니거나 payload Incident에 속하지 않은 hit를 센다.

`decision_source`는 `agent | rule_default | no_candidates`다. `decision_fallback`은 다음 값 또는
null이다.

```text
format_error
evidence_id_error
budget_exceeded
rate_limited
provider_error
log_error
not_in_candidates
decision_mismatch
similar_ticket_mismatch
incident_closed
```

후보 fallback과 판정 fallback은 독립적으로 기록한다. Agent Log에는 파이프 결정을 위한 새 행
종류를 추가하지 않는다.

### 저장 트랜잭션

`handle()` 시작 시 Ticket을 읽는다.

- `linked`면 성공한 no-op
- `escalated`가 아니면 처리하지 않음
- `escalated`면 문맥 조회·후보 선택·에이전트 호출 진행

LLM 호출 중에는 DB 트랜잭션이나 행 잠금을 유지하지 않는다.

저장 직전에 새 트랜잭션을 시작한다.

1. `SELECT status FROM tickets WHERE id = %s FOR UPDATE`
2. Ticket이 없거나 상태가 `escalated`가 아니면 저장 없이 롤백하고 종료
3. existing이면 선택한 Incident를 `FOR UPDATE`
4. Incident 상태를 다시 확인
5. Incident와 Ticket을 한 트랜잭션으로 저장

여러 워커 프로세스가 같은 Ticket을 동시에 처리해도 먼저 Ticket 잠금을 얻은 실행만 저장한다. 진
실행은 사용한 모델 토큰을 버리지만 중복 Incident나 중복 연결을 만들지 않는다.

기존 Incident 상태는 다음과 같이 처리한다.

- `analyzing`: 유지
- `awaiting_review`: `analyzing`으로 변경
- `human_handling`: 유지
- `confirmed`, `dismissed`, 삭제됨: 새 Incident 생성 및 `incident_closed` 기록

기존 Incident에는 Ticket ID를 중복 없이 추가하고 `Ticket.entities`를 기존 엔티티 뒤에 합친다.
`(type, normalize_entity_value(type, value))`가 같으면 기존 엔티티를 보존한다.

severity는 다음처럼 갱신한다.

```text
max(기존 Incident severity, 현재 Ticket의 Alert severity 최댓값)
```

현재 Ticket에 Alert가 없으면 현재 Ticket severity는 0이다. 전체 소속 Ticket과 Alert를 다시 읽어
severity를 재계산하지 않는다. Ticket은 Incident에 추가만 되고 계약상 severity는 소속 Alert 최댓값이므로
기존 값과 새 Ticket 값의 max가 같은 결과다. `updated_at`을 갱신하고 명시하지 않은 기존 분석 필드는
보존한다.

새 Incident는 다음 값으로 만든다.

- `id = new_id("inc")`
- `status = analyzing`
- `summary = null`
- `assessed_severity = null`
- `analysis_round = 0`
- `review_round = 0`
- `ticket_ids = [현재 Ticket]`
- `entities = Ticket.entities`
- `severity = 현재 Ticket Alert severity 최댓값`, 없으면 0
- `details = {}`

새 Incident 임시 제목 우선순위는 대표 Alert 제목, L3 Hunt 가설, 대표 Ticket 엔티티, Ticket ID다.
저장 전에 Incident와 Ticket 모두 `validate_contract()`를 통과시킨다.

### 커밋 뒤 Qdrant 적재

PostgreSQL 커밋 뒤 현재 Ticket 한 건만 적재한다.

- 컬렉션 목적: `ticket_branch`
- point ID: Ticket ID에서 `tkt_`를 제거한 UUIDv7
- vector: 분류에 사용한 임베딩 텍스트
- payload: `{"incident_id": 저장된 Incident ID}`

같은 point ID는 덮어쓴다. Ticket 텍스트는 이후 바꾸지 않는다. 적재 실패는 PostgreSQL 저장을
되돌리지 않고 재시도하지 않는다. Ticket 제목·본문·모델 출력은 로그에 쓰지 않고 실패 건수와 공개
오류 종류만 기록한다. `CollectionMissing`을 포함한 누락은 `reindex`로 복구한다. 임베딩 텍스트가
빈 Ticket은 적재하지 않는다.

### reindex

운영 명령은 다음과 같다.

```text
uv run python -m soc.l2 reindex [--recreate]
```

시작 시 일반 실행은 `ensure_collection()`을 호출해 없으면 만든다. `--recreate`는 현재 설정에서
파생한 컬렉션만 삭제한 뒤 `ensure_collection()`으로 다시 만든다. 시작 시 Qdrant 오류가 나면 복구
작업을 할 수 없으므로 종료 코드 1로 끝내고, 설정 오류는 종료 코드 2로 끝낸다.

일반 `reindex`도 컬렉션을 확인·생성하므로 Qdrant가 워커 시작 때 죽어 있다가 나중에 복구된 경우
워커 재시작 없이 컬렉션을 만들고 색인을 채울 수 있다.

처리는 다음과 같다.

- Incident의 `ticket_ids`와 linked Ticket을 PostgreSQL에서 읽는다.
- Ticket 문맥과 임베딩 텍스트를 다시 계산한다.
- 관계가 일관된 Ticket을 upsert한다.
- 빈 텍스트 Ticket은 정상 처리하되 point를 만들지 않는다.
- 한 Ticket이 여러 Incident에 있거나 어느 Incident에도 없으면 실패로 센다.
- Incident가 가리킨 Ticket이 없거나 linked가 아니어도 관계 실패로 센다.
- 일반 실행은 빠진 point를 채운다.
- `--recreate`는 기존 point를 모두 버리고 PostgreSQL에서 전체 색인을 다시 만든다.
- 처리·성공·실패 건수만 출력하고 레코드 내용과 내부 문자열은 출력하지 않는다.

종료 코드는 0 정상, 1 DB·Qdrant·임베더 오류, 2 설정 오류다.

### 워커와 실행기

`AgentWorker`는 다음 모양이다.

```text
stage = "l2"
name = "l2_branch"
poll(limit)
handle(ticket_id)
```

`poll`은 `status = escalated`인 Ticket ID를 오름차순으로 최대 `limit`개 반환한다. `handle`은 문맥
조회, 후보 조회, 에이전트 판정, 저장 직전 Ticket 잠금과 저장 트랜잭션, 커밋 뒤 Qdrant 적재 순으로
한 건을 처리한다.

`build_worker(config)`를 만들고 `[executor.l2].workers`에 등록한다.

```toml
workers = ["soc.l2.branch:build_worker"]
```

별도 분류 CLI는 만들지 않는다. 운영 CLI는 `reindex`만 둔다. `handle()` 안에서 새 이벤트 루프를
만들지 않고 DB 연결은 처리 건마다 연다.

## 바꿀 곳

### 결정

- `docs/decisions.md`: D-027에서 엔티티 등급·겹침을 제거하고 `vector | recent` 후보 경로와 실패
  시 새 Incident 규칙 반영

### 삭제

- `src/soc/l2/branch/signals.py`
- `src/soc/l2/branch/candidates.py`
- 신호 등급·겹침 테스트

### 수정

- `src/soc/l2/branch/__init__.py`: 문맥·후보 조회 분리, 워커 공개
- `src/soc/l2/branch/read.py`: recent 조회, ID 지정 Incident 조회, Ticket·제목 일괄 조회
- `src/soc/l2/branch/context.py`: signals 제거
- `src/soc/l2/config.py`: 네 설정 키와 `vector | recent` 검증
- `src/soc/agent/prompts/l2.md`: 분류·분석 공통 표현
- `src/soc/contracts/validate.py`: `branch_decision` 등록
- `config/default.toml`: L2 설정과 워커 등록
- `tests/contract_samples.py`
- `tests/fixtures/l2/branch.json`
- `tests/test_l2_config.py`
- `tests/test_l2_branch.py`
- `tests/test_l2_branch_db.py`
- `tests/fake_model.py`와 필요한 agent fixture

### 추가

- `src/soc/l2/branch/embed.py`
- `src/soc/l2/branch/decide.py`
- `src/soc/l2/branch/store.py`
- `src/soc/l2/branch/worker.py`
- `src/soc/l2/prompts/l2_classify.md`
- `src/soc/l2/__main__.py`
- `src/soc/l2/reindex.py`
- `contracts/branch_decision.schema.json`
- 생성된 Python 계약 코드
- 유효·무효 `branch_decision` fixture
- `docs/plans/250-l2-ticket-incident.md`
- `docs/notes/250-l2-ticket-incident.md`

### 변경하지 않음

- `src/soc/store/`
- D-013
- D-031
- DB 마이그레이션
- CI
- 새 환경변수와 `.env.example`

## 다른 코드와 맞물리는 곳

- #257의 `Embedder`, `VectorStore`, `CollectionMissing`, `CollectionMismatch`, `StoreError`를 사용한다.
- #226의 `build_branch()` 공개 구조가 바뀌고 기존 신호 모듈이 삭제된다. 현재 운영 호출자는 없으며
  관련 테스트를 함께 변경한다.
- `branch_decision` 계약 추가는 계약 모듈 변경이므로 계약 담당 승인 범위를 따른다.
- `[l2.branch]` 키 집합이 바뀌므로 해당 절을 로컬 설정에서 덮어쓴 환경은 새 네 키로 바꿔야 한다.
- `[executor.l2].workers`가 비어 있지 않게 되어 기본 `python -m soc.agent`가 L2 스레드를 시작한다.
- `src/soc/agent/prompts/l2.md` 변경으로 이후 L2 Agent Log의 `prompt_version`이 바뀐다.
- L2-B, 사람 검토, 화면 API는 바꾸지 않는다.

## 범위 밖

- 벡터 저장소·임베더와 의존성 변경
- 작업별 L2 도구 허용 목록
- L2-B Incident 분석
- 사람 검토·Case 등록
- Qdrant outbox와 PostgreSQL-Qdrant 원자적 저장
- 빠진 point 자동 감지와 자동 주기 복구
- Incident 병합과 Ticket 재배정
- 엔티티 겹침을 이용한 하이브리드 순위
- `incidents.entities` 인덱스와 DB 마이그레이션
- 실행 중 같은 차원의 다른 거리 방식 컬렉션 재생성 감지
- 실측에 따른 `top_k`, `max_candidates`, reasoning effort 조정

## 완료 기준

- [ ] D-027이 `vector | recent`와 실패 시 새 Incident 규칙으로 바뀌었다
- [ ] D-013과 D-031은 바뀌지 않았다
- [ ] 엔티티 등급·겹침 코드와 설정이 제거됐다
- [ ] vector 경로에서 열린 Incident 전수 조회가 실행되지 않는다
- [ ] 임베딩 텍스트가 레이블 없이 고정 순서와 빈 값 제외 규칙을 따른다
- [ ] 빈 텍스트가 `empty_text`로 recent에 가고 색인되지 않는다
- [ ] 모양이 잘못된 hit만 버리고 `invalid_hit_count`가 기록된다
- [ ] PostgreSQL 관계가 틀린 hit를 사용하지 않는다
- [ ] 최고 hit가 탈락하면 남은 hit 중 최고를 다시 선택한다
- [ ] 관계 검사 뒤 같은 유사도 기준으로 최종 후보를 다시 정렬한다
- [ ] 탈락 후보 자리를 다음 순위 Incident로 채우지 않는다
- [ ] 최종 후보가 모두 제거되면 `no_valid_candidates → recent`로 진행한다
- [ ] recent가 시간 창 안 열린 Incident를 `updated_at` 내림차순으로 고른다
- [ ] 후보가 없으면 모델을 부르지 않는다
- [ ] `branch_decision` 계약과 생성 코드·fixture가 있다
- [ ] new 결정은 `similar_ticket_ids`가 비어야 한다
- [ ] 실제 Incident 존재와 후보 포함 여부를 코드가 검사한다
- [ ] 에이전트 실패와 코드 검사 실패가 새 Incident로 간다
- [ ] `cancelled`는 저장하지 않는다
- [ ] Ticket을 저장 직전에 잠그고 상태를 재확인한다
- [ ] 기존 Incident severity가 기존 값과 새 Ticket 값의 max로 갱신된다
- [ ] Incident·Ticket이 한 트랜잭션으로 저장된다
- [ ] 저장 뒤 Ticket이 Qdrant에 적재된다
- [ ] upsert 실패는 PostgreSQL 결과를 되돌리지 않는다
- [ ] 워커와 일반 reindex가 시작 시 `ensure_collection()`을 호출한다
- [ ] `reindex`와 `--recreate`가 동작한다
- [ ] L2 워커가 실행기에 등록된다
- [ ] 실제 BGE-M3·Qdrant·모델로 일반·L3 Ticket과 유사도 점수 분포를 확인하고 수치만 기록한다
- [ ] `uv run python scripts/generate_contracts.py --check`가 통과한다
- [ ] `uv run ruff format --check .`가 통과한다
- [ ] `uv run ruff check .`가 통과한다
- [ ] `uv run pytest`가 통과한다
- [ ] `uv run pytest -m "db or qdrant"`가 통과한다
- [ ] 확정 계획과 개발 기록이 있다

## 토론으로 정한 것

1. 후보 경로 이름 `direct`를 `recent`로 바꾼다. 이 경로는 엔티티 비교가 아니라 최근 열린
   Incident 조회이기 때문이다.
2. #257 저장소는 수정하지 않고 워커 시작 시 `ensure_collection()`을 한 번 호출한다.
3. 일반 `StoreError`는 경고 후 워커를 시작해 건별 recent fallback을 유지하고,
   `CollectionMismatch`는 시작 실패로 처리한다.
4. 일반 reindex도 `ensure_collection()`을 호출해 워커 재시작 없이 컬렉션을 만들 수 있게 한다.
5. Ticket은 LLM 호출 전에 잠그지 않고 저장 직전에 잠근다.
6. 빈 임베딩 텍스트는 `empty_text`로 구분한다.
7. 임베딩 텍스트에는 레이블을 넣지 않고 줄바꿈으로만 연결한다.
8. 모양이 잘못된 Qdrant hit는 해당 hit만 버린다.
9. PostgreSQL이 부정한 Ticket-Incident 관계는 후보 근거로 사용하지 않는다. 앞서 제안한 “Incident
   후보 유지” 안은 철회했다.
10. 최고 hit가 관계 검사에서 탈락하면 남은 hit 중 최고를 다시 선택하고 같은 유사도 기준으로
    재정렬한다.
11. 탈락한 후보 자리는 다음 순위 Incident로 채우지 않는다.
12. 버린 hit 수를 Ticket details에 기록한다.
13. new의 빈 `similar_ticket_ids`는 Draft-07 계약으로 강제한다.
14. 계약은 Incident ID 모양만 검사하고 실제 존재와 후보 포함 여부는 코드가 검사한다.
15. 후보 기간은 `updated_at - created_at`이다.
16. Incident 엔티티는 `Ticket.entities`만 사용한다.
17. 기존 Incident severity는 전체 재계산하지 않고 기존 값과 새 Ticket 값의 max로 갱신한다.
18. 기본값은 이번 이슈에서 조정하지 않으며 실측은 후속 이슈 입력이다.
19. 실행 중 컬렉션 교체 감지는 범위 밖이다.
20. upsert의 `CollectionMissing`은 기록 후 넘기고 `reindex`로 복구한다.

## 바뀐 점
