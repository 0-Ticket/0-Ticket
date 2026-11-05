---
issue: 261
date: 2026-11-06
owner: Juhyeok0603
supersedes: []
---

# L2-B Incident 분석: 타임라인·ATT&CK·영향 범위·탐지 룰 제안 만들기

## 목표

`status = analyzing`인 Incident를 하나씩 읽고, 소속 Ticket의 근거와 읽기 전용 도구 조회로
분석 보고서를 만든다. `not_threat`은 `dismissed`로 종결하고, `attempted`·`succeeded`·
`inconclusive`는 Artifact와 제안을 저장해 `awaiting_review`로 넘긴다.

L2에서 도구를 실제 사용하는 첫 작업이다. `[tools.allowed] l2`의 도구 8개를 등록하고, 최상위와
중첩된 모든 근거 ID를 근거 장부로 검증한다.

## 방법

### 선행 조건과 결정

- #250의 L2 분류 워커, #215의 실행기와 `AgentWorker`, #209의 `run_task`·`AgentTask`, #210의
  프롬프트 계층을 그대로 쓴다.
- `src/soc/agent/prompts/l2.md`의 기존 분석 지시는 고치지 않는다.
- 새 라이브러리는 추가하지 않는다.
- D-028은 새 Ticket이 자동 분석 가능한 Incident에 붙었을 때만 자동 재분석한다는 뜻으로
  명확히 한다. `awaiting_review`는 `analyzing`으로 되돌리지만 `human_handling`은 유지한다.
- L2 분석 결과 저장 방식(D-045): 성공한 분석 라운드마다 Artifact 한 행을 쌓고, 탐지 룰·대응
  방안 제안은 Proposal 한 건씩 저장한다. 실패한 라운드는 Artifact가 없어 번호에 빈칸이 생길 수
  있다.
- Incident Artifact와 Proposal은 L2가 쓰고 사람 검토가 읽는 단계 데이터로
  `docs/architecture.md`에 올린다.

### 테이블과 ID

마이그레이션 `0200_incident_artifacts.sql`에 다음 테이블을 만든다.

```sql
CREATE TABLE incident_artifacts (
    id text PRIMARY KEY,
    incident_id text NOT NULL REFERENCES incidents (id),
    analysis_round integer NOT NULL CHECK (analysis_round >= 1),
    verdict text NOT NULL CHECK (
        verdict IN ('not_threat', 'attempted', 'succeeded', 'inconclusive')
    ),
    summary text NOT NULL CHECK (summary <> ''),
    assessed_severity smallint NOT NULL CHECK (assessed_severity BETWEEN 0 AND 6),
    timeline jsonb NOT NULL CHECK (jsonb_typeof(timeline) = 'array'),
    techniques jsonb NOT NULL CHECK (jsonb_typeof(techniques) = 'array'),
    impact text NOT NULL,
    cause text NOT NULL,
    further_risk text NOT NULL,
    evidence_ids text[] NOT NULL CHECK (array_position(evidence_ids, NULL) IS NULL),
    created_at timestamptz NOT NULL,
    UNIQUE (incident_id, analysis_round)
);

CREATE INDEX incident_artifacts_incident_idx ON incident_artifacts (incident_id);

CREATE TABLE incident_proposals (
    id text PRIMARY KEY,
    artifact_id text NOT NULL REFERENCES incident_artifacts (id),
    kind text NOT NULL CHECK (kind IN ('detection_rule', 'response_action')),
    seq integer NOT NULL CHECK (seq >= 1),
    body text NOT NULL CHECK (body <> ''),
    created_at timestamptz NOT NULL,
    UNIQUE (artifact_id, kind, seq)
);

CREATE INDEX incident_proposals_artifact_idx ON incident_proposals (artifact_id);
```

- `incident_artifacts`와 `incident_proposals`에는 쓰임이 없는 `details`·`status`를 두지 않는다.
- Proposal에 `incident_id`를 복제하지 않고 `artifact_id`로 조인한다.
- `incidents` 테이블에는 새 컬럼을 만들지 않는다.
- ID 접두사 `art`(Artifact), `prp`(Proposal)를 `src/soc/ids.py`와 공통 타입 계약에 추가한다.
- Incident 계약의 `entities` 설명을 "소속 Ticket 엔티티와 L2 조사에서 근거와 함께 확인한
  엔티티를 모은 것"으로 바꾼다.
- `art`·`prp` 접두사와 Incident `entities` 의미 변경은 L1·L2·L3·화면 담당 승인 범위다.

### 계약

다음 계약 네 개를 추가하고 `_CONTRACTS`에 등록한다.

| 계약 | 용도 |
|---|---|
| `incident_findings` | run 1 모델 출력 |
| `incident_analysis` | run 2 모델 출력 |
| `incident_artifact` | 저장되는 Artifact 행 |
| `incident_proposal` | 저장되는 Proposal 행 |

`incident_findings`는 사실만 담는다.

| 필드 | 규칙 |
|---|---|
| `timeline` | `{time, summary, evidence_ids}` 목록. 항목마다 근거가 1개 이상 |
| `entities` | `{entity, evidence_ids}` 목록. 항목마다 근거가 1개 이상 |
| `evidence_ids` | 어느 항목에도 붙지 않은 근거. 비어도 됨 |

`incident_analysis` 필드:

| 필드 | 규칙 |
|---|---|
| `verdict` | `not_threat`·`attempted`·`succeeded`·`inconclusive` |
| `summary` | 빈 문자열이 아닌 요약 |
| `assessed_severity` | 0~6 |
| `techniques` | 기법 ID와 근거 목록. 이름은 모델이 내지 않고 각 항목의 근거는 1개 이상 |
| `impact` | 확인하지 못했으면 빈 문자열 |
| `cause` | 확인하지 못했으면 빈 문자열 |
| `further_risk` | 추가 침해 가능성 |
| `detection_rules` | 빈 문자열이 아닌 자유 문장 목록 |
| `response_actions` | 빈 문자열이 아닌 자유 문장 목록 |
| `evidence_ids` | 어느 기법에도 붙지 않은 근거. 비어도 됨 |

모델은 기법 ID와 근거만 내고, 코드는 `[l3.intel.attack] version`의 `attack_techniques`에서 이름을
찾아 Artifact에 붙인다. 없는 ID는 버리고 수를
`incidents.details.l2_analyze.dropped_techniques`에 기록한다.

코드는 run 1·2의 최상위와 중첩 근거를 모두 모아 Artifact `evidence_ids`를 만든다.

- `not_threat`·`attempted`·`succeeded` Artifact는 timeline과 합집합 근거가 비어 있지 않아야 한다.
- timeline 항목은 근거가 1개 이상이다.
- `inconclusive`만 빈 timeline을 허용한다.
- `not_threat`도 Incident를 종결하는 판정이므로 근거를 요구한다.

### 문맥, 조회 구간, 자산

Incident에서 다음을 읽는다.

- Incident와 `ticket_ids`
- 소속 Ticket·Alert
- L3 Ticket이면 Hunt
- Ticket `verdict.evidence_ids`와 Hunt `evidence_ids`가 가리키는 Event·Agent Log
- 이전 성공 Artifact 중 `analysis_round`가 가장 큰 한 행
- Incident 엔티티에 해당하는 자산
- 설정 버전의 ATT&CK 기법 이름

`soc.l2.branch.read.read_branch_data()`를 Ticket별로 재사용하되 `linked` 상태를 읽는다. 소속 Ticket을
하나도 읽지 못하면 모델을 부르지 않고 Incident를 `analyzing`으로 남긴다.

조회 구간은 코드가 계산한다.

```text
requested_from = 가장 이른 Ticket created_at - lookback_ms
window.from    = max(requested_from, now - max_range_days)
window.to      = now
```

`data.window`에는 `from`, `to`, `truncated`, 원래 시작 시각을 넣는다. 잘렸으면 그 이전을 조회하지
않았다고 모델에 알린다. 1단계 관련 기록 조회와 모델 도구가 같은 window를 쓴다.

기존 `lookup_assets()`와 `[asset_lookup].statement_timeout_ms`를 쓴다. 실패해도 분석을 계속하되
`data.asset_lookup_failed = true`로 두 run에 알리고
`incidents.details.l2_analyze.asset_lookup_failed`에 기록한다.

### 1단계 관련 기록 조회

모델 호출 전에 L2 워커 PostgreSQL 연결로 직접 조회한다.

- Incident 엔티티를 최대 `max_seed_entities`개 사용한다.
- 각 엔티티로 window 안의 Alert와 Event를 조회한다.
- Alert와 Event를 합쳐 최신 `max_related_per_entity`건을 고른다.
- 고른 결과는 시간 오름차순으로 `data.related`에 넣는다.
- 실제 전달한 ID만 `allowed_evidence_ids`에 추가한다.

### 근거 장부

run 1의 초기 근거 장부는 문맥에서 실제 존재를 확인한 Alert·Event·Agent Log ID와 1단계 조회 ID다.
run 1의 `cited_ids`는 최상위 근거, `timeline[].evidence_ids`, `entities[].evidence_ids`를 평탄화한다.

run 2의 초기 근거 장부는 run 1이 인용한 모든 근거의 평탄화 결과와 문맥 ID다. run 2의
`cited_ids`는 최상위 근거와 `techniques[].evidence_ids`를 평탄화한다.

`runner.py`가 평탄화된 모든 ID를 장부와 대조한다. 저장 근거는 run 1·2 전체 근거의 합집합을
코드가 만들므로 별도 부분집합 검사는 두지 않는다.

### 에이전트 두 번 실행

| | run 1 | run 2 |
|---|---|---|
| 작업 | `l2_investigate` | `l2_report` |
| 도구 | 사용 | 사용하지 않음 |
| 입력 | 문맥·related·자산·window·이전 Artifact | run 1 출력·Incident 요약·자산·이전 Artifact |
| 계약 | `incident_findings` | `incident_analysis` |

두 작업 모두 `stage="l2"`, `subject_type="incident"`, `subject_id=<Incident ID>`,
`attempt=analysis_round + 1`이다. 4층 프롬프트는 `src/soc/l2/prompts/l2_investigate.md`와
`l2_report.md`에 두고 금지 문구 검사를 통과시킨다.

도구 목록은 `AgentTask`에 넣지 않고 stage의 허용 목록으로 정한다. `run_host_check`는 SSH 호스트
설정이 비면 등록되지 않으며, 그 상태에서도 분석이 끝나야 한다.

### 결과, 재시도, 라운드

| 결과 | 처리 |
|---|---|
| `not_threat` | Artifact 저장 후 `dismissed` |
| `attempted`·`succeeded`·`inconclusive` | Artifact 저장 후 `awaiting_review` |
| `cancelled` | 저장 없이 `analyzing` 유지 |
| 다른 실패 | Artifact 없이 `analysis_round`만 올리고 `analyzing` 유지 |

run 1은 같은 라운드에서 재시도하지 않는다. run 2는 `provider_error`·`rate_limited`·`log_error`만
같은 run 1 결과로 한 번 더 부른다. `format_error`·`evidence_id_error`·`budget_exceeded`·
`cancelled`는 다시 부르지 않는다. `run_task`가 형식 오류를 이미 한 번 재요청하기 때문이다.

`log_error` 결과는 감사 기록이 없으므로 Artifact로 저장하지 않는다. run 1 또는 최종 run 2가
실패하면 그 라운드를 실패로 세고 Artifact를 저장하지 않는다. `cancelled`만 round로 세지 않는다.

poll 조건:

```text
status = analyzing
AND (
    analysis_round < max_analysis_rounds
    OR (analysis_round >= max_analysis_rounds AND stopped가 없음)
)
```

한도에 닿은 Incident는 한 번 더 poll해 모델을 부르지 않고
`details.l2_analyze.stopped = "round_limit"`을 기록한 뒤 제외한다.

### 저장 트랜잭션

모델 호출 중에는 트랜잭션이나 행 잠금을 유지하지 않는다. 저장 직전에 Incident를 `FOR UPDATE`로
읽고 `status`와 처음 읽은 `analysis_round`를 확인한다. 달라졌으면 저장하지 않는다.

한 트랜잭션에서 다음을 처리한다.

1. `analysis_round + 1`의 Artifact 삽입
2. 탐지 룰·대응 방안을 Proposal 행으로 분해해 모델 순서대로 삽입
3. Incident의 `summary`·`assessed_severity`·`status`·`analysis_round`·`updated_at` 갱신
4. 근거가 붙은 조사 엔티티만 `(type, normalize_entity_value(type, value))` 기준으로 합침
5. Incident·Artifact·Proposal 계약 검증

Ticket은 건드리지 않고 `linked`로 둔다.

### 워커와 설정

새 워커는 `stage="l2"`, `name="l2_analyze"`다. `poll(limit)`은 조건에 맞는 Incident를
`updated_at` 오름차순으로 반환한다. `handle()`은 문맥 → window·자산·관련 기록 → 두 run → 기법
검사 → 저장 순으로 실행한다. DB 연결은 handle마다 열고 이벤트 루프를 만들지 않는다.

```toml
[executor.l2]
workers = ["soc.l2.branch:build_worker", "soc.l2.analyze:build_worker"]

[l2.analyze]
lookback_ms = 86_400_000
max_analysis_rounds = 5
max_seed_entities = 10
max_related_per_entity = 20
```

네 설정은 모두 양의 정수이고 예상 밖 키는 거부한다. `[l2.branch]`는 바꾸지 않는다.

## 바꿀 곳

### 추가

- `src/soc/db/migrations/0200_incident_artifacts.sql`
- `src/soc/l2/analyze/__init__.py`, `read.py`, `decide.py`, `store.py`, `worker.py`
- `src/soc/l2/prompts/l2_investigate.md`, `l2_report.md`
- `contracts/incident_findings.schema.json`, `incident_analysis.schema.json`,
  `incident_artifact.schema.json`, `incident_proposal.schema.json`
- 위 계약의 생성 코드와 유효·무효 fixture
- `tests/fixtures/l2/analyze.json`
- `tests/test_l2_analyze.py`, `tests/test_l2_analyze_db.py`
- `docs/notes/261-l2-incident-analysis.md`

### 수정

- `docs/architecture.md`: 단계 데이터에 Incident Artifact·Proposal 추가
- `docs/decisions.md`: D-045 추가, D-028 문구와 기록 갱신
- `contracts/incident.schema.json`: `entities` 설명 변경과 생성 코드 갱신
- `contracts/common/types.schema.json`: `artifact_id`·`proposal_id`
- `src/soc/ids.py`: `art`·`prp`
- `src/soc/contracts/validate.py`: 계약 네 개 등록
- `src/soc/l2/config.py`, `config/default.toml`: 분석 설정과 워커
- `tests/contract_samples.py`

### 변경하지 않음

- `incidents` 테이블 구조
- `src/soc/l2/branch/` 동작
- `src/soc/agent/prompts/l2.md`
- `src/soc/store/`, `src/soc/tools/`
- D-027, Ticket 테이블·계약, CI, Case 생성, 사람 검토

## 다른 코드와 맞물리는 곳

- `art`·`prp`와 Incident `entities` 의미는 공통 계약 변경이다.
- 화면은 후속 이슈에서 Artifact와 Proposal을 읽는다. 이번 이슈는 쓰기만 한다.
- 에이전트 DB 읽기 역할에는 새 테이블 권한을 주지 않는다.
- L2 실행기에서 분류와 분석 워커가 같은 스레드로 번갈아 돈다.
- `soc.l2.branch.read`의 Ticket 문맥 조회를 분석도 사용한다.
- ATT&CK 이름은 `[l3.intel.attack] version`의 테이블을 읽는다.
- SIEM·SSH 설정은 분석 품질에 영향을 주지만 도구 코드는 바꾸지 않는다.

## 범위 밖

- 사람 검토·반려, `review_round` 증가, Case 생성
- Incident 화면과 API, Proposal 채택·기각·status
- 반려 사유 저장과 그에 따른 재분석
- 자동 차단·격리, 탐지 룰의 SIEM 적용
- HTTP Payload와 맺어진 네트워크 연결 조회 도구
- ATT&CK 기법 ID 검색 색인, Incident 병합, Ticket 재배정
- 실측에 따른 기본 설정값 조정

## 완료 기준

- [ ] 마이그레이션 0200이 `incident_artifacts`·`incident_proposals`를 만든다
- [ ] D-045가 L2 절에 있고 결정 기록이 있다
- [ ] `incidents` 테이블이 바뀌지 않았다
- [ ] Incident 계약의 `entities` 설명이 조사 엔티티를 포함한다
- [ ] 근거 ID가 없는 조사 엔티티는 합쳐지지 않는다
- [ ] window가 `max_range_days`를 넘지 않고 잘린 사실이 입력에 들어간다
- [ ] `provider_error`·`rate_limited`·`log_error`만 run 2를 한 번 더 부르고 run 1은 재시도하지 않는다
- [ ] 한도 도달 Incident가 `stopped`를 남긴 뒤 poll에서 빠진다
- [ ] `art`·`prp`가 ID 코드와 공통 타입 계약에 있다
- [ ] 계약 네 개와 생성 코드·fixture가 있다
- [ ] verdict가 네 값이고 conclusive Artifact의 합집합 `evidence_ids`가 비지 않는다
- [ ] `inconclusive`가 `awaiting_review`로 가고 `analyzing`에 남지 않는다
- [ ] Proposal이 개별 행으로 저장되고 `kind`·`seq`가 모델 순서를 지킨다
- [ ] 같은 `(incident_id, analysis_round)`를 두 번 저장할 수 없다
- [ ] Artifact·Proposal·Incident가 한 트랜잭션으로 저장된다
- [ ] 재분석이 이전 Artifact를 문맥에 넣는다
- [ ] 근거 ID 없는 기법을 계약이 거부한다
- [ ] `not_threat`도 비어 있지 않은 timeline과 근거를 요구한다
- [ ] 중첩 근거까지 장부로 검사되고 저장 `evidence_ids`가 합집합이다
- [ ] 자산 조회 실패가 분석을 멈추지 않고 두 run과 Incident details에 알려진다
- [ ] 버린 기법 수가 `incidents.details.l2_analyze`에 남는다
- [ ] 조회 구간을 코드가 계산해 `data.window`로 넘기고 프롬프트가 그대로 쓰게 한다
- [ ] `allowed_evidence_ids`에 실제 존재를 확인한 ID만 들어간다
- [ ] 설정 버전에 없는 ATT&CK 기법을 버리고 수를 기록한다
- [ ] `not_threat`은 `dismissed`, 나머지 셋은 `awaiting_review`가 된다
- [ ] 분석 실패는 Incident를 종결하지 않고 `analyzing`으로 남긴다
- [ ] run 2 실패 시 run 1의 도구 호출을 반복하지 않는다
- [ ] 자산 정보가 워커 연결로 조회돼 문맥에 들어간다
- [ ] `cancelled`는 아무것도 저장하지 않는다
- [ ] `analysis_round` 한도에서는 모델을 부르지 않고 멈춘 사실을 남긴다
- [ ] 저장 직전 `status`·`analysis_round`를 다시 확인한다
- [ ] `handle()`이 멱등이다
- [ ] `summary`·`assessed_severity`가 Incident의 기존 칸에도 들어간다
- [ ] SSH 호스트 설정 없이도 분석이 끝난다
- [ ] L2 워커 두 개가 실행기에 등록된다
- [ ] 실제 모델로 일반·L3 Incident를 확인하고 수치만 기록한다
- [ ] `uv run python scripts/generate_contracts.py --check`가 통과한다
- [ ] `uv run ruff format --check .`가 통과한다
- [ ] `uv run ruff check .`가 통과한다
- [ ] `uv run pytest`가 통과한다
- [ ] `uv run pytest -m "db or qdrant"`가 통과한다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다

## 토론으로 정한 것

- 자동 재분석은 `awaiting_review`에만 적용하고 `human_handling`은 유지한다.
- 근거가 붙은 조사 엔티티만 Incident에 합치고 계약 설명을 바꾼다.
- conclusive는 timeline과 전체 근거를 요구하며 `inconclusive`만 빈 timeline을 허용한다.
- Proposal은 자유 문장으로 두고 쓰임 없는 `details`·`status`를 만들지 않는다.
- 실패도 round로 세고, 성공한 round만 Artifact를 남긴다.
- 한도에 닿은 Incident를 한 번 더 poll해 `stopped`를 기록한다.
- run 2는 일시 실패 세 종류만 한 번 다시 부르고 run 1은 재시도하지 않는다.
- window를 도구 한도 안으로 자르고 잘린 사실을 모델에 알린다.
- ATT&CK 버전과 자산 timeout은 기존 설정을 재사용한다.
- Artifact·Proposal을 아키텍처의 단계 데이터로 올린다.
- 최상위와 중첩 근거를 평탄화해 검사하고, 저장 근거 합집합은 코드가 만든다.
- `log_error` 결과는 감사 기록이 없으므로 Artifact로 저장하지 않는다.

## 바뀐 점
