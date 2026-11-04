---
issue: 226
date: 2026-11-04
owner: Juhyeok0603
supersedes: []
---

# Ticket 분류 문맥과 Incident 후보 고르기

## 목표

`status = escalated`인 Ticket 하나에서 분류 문맥과 엔티티 신호를 만들고, 시간 창 안의 열린 Incident를 겹치는 신호 순으로 정렬해 상위 후보를 돌려준다. 이 단계는 DB를 읽기만 하며 에이전트 호출·판정·저장은 하지 않는다.

## 방법

### 설정

`soc.l2.config.load_config()`가 `config/default.toml` 위에 `config/local.toml`을 덮어쓰고 `[l2]`만 돌려준다. L3 로더와 같은 모양을 따르고, 공통 설정 로더가 생길 때까지 코드를 공유하기 위한 새 추상화는 만들지 않는다.

`[l2.branch]`에는 아래 값만 둔다.

```toml
candidate_window_ms = 86400000
max_candidates = 5
strong_signal_types = ["file_hash", "process", "url", "domain", "user"]
weak_signal_types = ["ip", "host"]
shared_entity_values = []
```

`candidate_window_ms`와 `max_candidates`는 양의 정수여야 한다. 신호 목록은 Entity `type` enum 안의 값이어야 하고 강한·보조 목록이 겹치면 안 된다. 잘못된 설정은 L3 선례처럼 `ConfigError`로 멈춘다. 공용 엔티티의 빈도 임계값은 근거가 쌓이기 전에는 넣지 않는다.

### DB 조회와 순수 계산의 경계

`src/soc/l2/branch/read.py`는 DB 행을 읽는 얇은 계층으로 둔다.

1. 대상 Ticket을 읽어 존재하고 `status = escalated`인지 확인한다.
2. `alert_ids`의 Alert를 읽는다.
3. `origin = l3`이면 `hunt_id`의 Hunt를 읽는다.
4. Ticket `verdict.evidence_ids`와 Hunt `evidence_ids`를 합쳐 중복을 없애고, `alt_`·`evt_`·`agl_`를 각각 `alerts`·`events`·`agent_logs`에서 확인한다. 없는 ID는 빼고 개수만 센다. `verdict`가 null이면 Ticket 쪽 근거는 빈 목록이며 없는 근거도 0건이다.
5. Event는 위 근거 목록에 실제로 존재하는 `evt_` ID로만 읽는다. Alert와 Event 사이의 없는 연결을 추정하지 않는다.
6. 호출자가 넘긴 `now: datetime`을 기준으로 `updated_at`이 `candidate_window_ms` 안이고 `status`가 `analyzing`·`awaiting_review`·`human_handling`인 Incident를 읽는다. 상태 조건이 `incidents_status_idx`를 쓸 수 있는 모양을 유지한다.

`context.py`·`signals.py`·`candidates.py`는 DB 연결 없이 조회 결과만 받아 계산하는 순수 함수로 둔다. L2-A-2가 그대로 받을 수 있도록 결과는 frozen dataclass로 돌려주되, 에이전트 입력 직렬화는 L2-A-2에서 한다.

### 분류 문맥

문맥에는 Ticket, `alert_ids`의 Alert, 근거가 확인된 Event, L3 Ticket의 Hunt, 확인된 근거 ID, 없는 근거 건수를 담는다. Hunt의 `hypothesis`와 `reason`을 포함해 모든 밖에서 온 문자열은 데이터로만 보존하고 이 단계에서 지시로 해석하거나 화면 형식으로 렌더링하지 않는다.

공용 엔티티도 문맥에서 지우지 않는다. `role`은 원래 값을 보존하지만 후보 겹침 비교에는 쓰지 않는다.

### 엔티티 정규화와 등급

Ticket·Incident 엔티티에 같은 정규화 함수를 쓰고, L3 Ticket에서는 Hunt 엔티티에도 적용한다. 비교 키는 `(type, 정규화한 value)`다.

- 모든 값에 `strip()`을 적용한다.
- `host`·`domain`·`file_hash`·`user`는 소문자로 바꾼다.
- `ip`는 `ipaddress`로 읽히면 정규 표기로 바꾸고, 읽히지 않으면 공백을 뺀 값을 소문자로 보존한다.
- `url`·`process`는 대소문자가 뜻을 가질 수 있으므로 공백만 뺀다.
- `role`은 정규화하지 않고 비교 키에서도 제외한다.

정규화한 값이 `shared_entity_values`에 있으면 type과 관계없이 공용 등급이 우선한다. 그 밖에는 `strong_signal_types`와 `weak_signal_types`로 강한·보조 등급을 매긴다. L3 Ticket은 Ticket과 Hunt의 엔티티를 Ticket 쪽 신호로 합치며, 중복 비교 키는 한 번만 센다.

`user` 소문자화는 AD·Windows 계정이 대소문자를 구분하지 않는 경우가 더 흔하다는 전제로 택한다. Linux에서 대소문자가 다른 계정을 하나로 합칠 수 있다는 한계와 이 선택의 이유는 개발 기록에 남긴다.

### 후보 순위

조회된 Incident마다 Ticket 쪽 신호와 겹치는 강한·보조 비교 키의 수를 센다. 공용 엔티티는 겹쳐도 점수에서 빼되 문맥에는 남긴다. 시간 근접 점수나 별도 시간 임계값은 두지 않는다. 후보 집합을 이미 `candidate_window_ms`로 제한했기 때문이다.

후보는 `(강한 겹침 수, 보조 겹침 수, updated_at)` 내림차순으로 정렬하고 상위 `max_candidates`개만 반환한다. 열린 Incident를 엔티티 교집합으로 DB에서 거르지 않고 모두 읽어 코드에서 세며, jsonb 인덱스나 마이그레이션은 추가하지 않는다.

### 샘플과 테스트

먼저 `tests/fixtures/l2/`에 손으로 만든 Ticket·Alert·Event·Hunt·Incident 샘플을 둔다. 계약 대상 샘플은 기존 `tests/contract_samples.py` 흐름으로 `validate_contract`를 거쳐 샘플 자체가 계약과 맞는지도 확인한다.

- 기본 `uv run pytest`: 설정 검증, 문맥 구성, Ticket·Hunt 양쪽 근거 확인, 없는 근거 집계, null verdict, 엔티티 정규화·등급·중복 제거, 공용 엔티티 보존과 점수 제외, 후보 순위와 개수 상한을 순수 함수로 확인한다.
- `db` 마커 테스트: Ticket·Alert·Event·Hunt 조회, 근거 ID별 존재 확인, Incident 상태·시간 창 필터, `incidents_status_idx`를 쓸 수 있는 조회를 확인한다.

## 바꿀 곳

- `src/soc/l2/__init__.py`, `src/soc/l2/config.py`: L2 설정 로더와 설정 오류
- `src/soc/l2/branch/__init__.py`: L2-A-2가 쓸 읽기 전용 진입점과 결과 타입 공개
- `src/soc/l2/branch/read.py`: Ticket 문맥과 열린 Incident DB 조회
- `src/soc/l2/branch/context.py`: 조회 결과로 분류 문맥 구성
- `src/soc/l2/branch/signals.py`: 엔티티 정규화와 강한·보조·공용 등급
- `src/soc/l2/branch/candidates.py`: 겹침 수 계산과 후보 정렬
- `config/default.toml`: `[l2.branch]` 기본값
- `tests/fixtures/l2/`: 손으로 만든 계약 샘플과 후보 샘플
- `tests/test_l2_config.py`, `tests/test_l2_branch.py`: 설정과 순수 계산 테스트
- `tests/test_l2_branch_db.py`: `db` 마커 조회 테스트
- `docs/notes/226-l2-branch.md`: 개발 기록과 `user` 정규화 한계

## 다른 코드와 맞물리는 곳

- `config/default.toml`에 새 `[l2.branch]` 절이 생긴다. 기존 설정 절은 바꾸지 않는다.
- L2-A-2가 이 모듈의 frozen dataclass 결과를 에이전트 입력으로 직렬화한다. 이번 이슈에서는 에이전트용 계약이나 직렬화 형식을 만들지 않는다.
- 기존 공통 계약과 DB 테이블을 읽기만 한다. 계약·마이그레이션·기존 설정 키는 바꾸지 않는다.

## 범위 밖

- 에이전트 호출, 분류 출력 계약, 4층 프롬프트
- 최종 Incident 선택, 규칙 기본값, DB 쓰기와 상태 전이, 저장 트랜잭션
- 워커 등록, 주기 실행, 실제 모델 확인
- 공용 엔티티 빈도 판정과 `shared_frequency_threshold`
- 엔티티 jsonb 인덱스와 새 마이그레이션

## 완료 기준

- [ ] `tests/fixtures/l2/`에 손으로 만든 작은 Ticket·Alert·Event·Hunt·Incident 샘플이 있고 계약 대상은 `validate_contract`를 통과한다
- [ ] `escalated` Ticket 하나로 Ticket·Alert·근거 Event를 포함한 분류 문맥이 만들어진다
- [ ] `origin = l3`이고 `alert_ids`가 빈 Ticket도 Hunt와 Hunt의 `evt_` 근거·엔티티로 문맥과 신호가 만들어진다
- [ ] Ticket·Hunt 근거의 `alt_`·`evt_`·`agl_` 존재를 확인하고, 없는 근거만 빼고 건수를 기록하며, null verdict는 근거 0건으로 진행한다
- [ ] Ticket·Incident·Hunt 엔티티에 같은 type별 정규화를 적용하고 `role`은 보존하되 비교에서 제외한다
- [ ] 엔티티가 강한·보조·공용 세 등급으로 나뉘며 공용 등급이 우선한다
- [ ] 후보는 열린 Incident(`analyzing`·`awaiting_review`·`human_handling`) 중 시간 창 안에서만 나온다
- [ ] 후보 순위가 `(강한 겹침 수, 보조 겹침 수, updated_at)` 내림차순이고 상위 `max_candidates`개다
- [ ] 공용 엔티티는 점수에서 빠지고 문맥에는 남는다
- [ ] `read.py`의 DB 조회를 제외한 문맥·신호·순위 계산이 기본 `uv run pytest`에서 확인된다
- [ ] DB 조회의 상태·시간 창 필터와 `incidents_status_idx` 사용을 `db` 마커 테스트로 확인한다
- [ ] `[l2.branch]` 기본값이 `config/default.toml`에 있고 잘못된 설정은 `ConfigError`다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`가 통과하며 `db` 마커 테스트도 따로 통과한다
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다

## 토론으로 정한 것

1. **D-027·D-028이 머지된 뒤 최신 `origin/main`에서 시작한다.** 검토 당시 결정 커밋이 로컬 브랜치에만 있어 먼저 결정 PR을 머지하기로 했다. 두 결정은 #229·#230으로 `origin/main`에 들어왔다.
2. **Event는 실제 근거의 `evt_` ID로만 읽는다.** 이슈 본문의 Alert→Event 연결은 계약과 DB에 없었다. Ticket verdict뿐 아니라 L3 Hunt의 근거도 함께 확인하며, 시각·엔티티로 관계를 추정하지 않는다.
3. **공용 엔티티는 설정 목록으로만 판정한다.** `shared_frequency_threshold`는 열린 Incident가 적을 때 동작하지 않고 기본값의 근거도 없어 뺐다. 빈도 판정은 기록이 쌓인 뒤 별도 이슈에서 정한다.
4. **보조 신호에 시간 근접 점수를 쓰지 않는다.** 후보 집합을 이미 시간 창으로 제한하므로 보조 겹침 수만 세고 `updated_at`을 세 번째 정렬 키로 쓴다.
5. **Ticket·Incident·Hunt 엔티티를 type별로 같은 방식으로 정규화한다.** 전부 소문자로 만들면 URL 경로와 프로세스 경로를 잘못 합칠 수 있어 `url`·`process`는 대소문자를 보존한다. `user`는 AD·Windows를 우선해 소문자화하되 Linux 계정 충돌 한계를 기록한다.
6. **DB 조회와 순수 계산을 분리한다.** 기본 pytest가 `db` 테스트를 제외하므로, 문맥·신호·순위 계산을 순수 함수로 두어 기본 검사에서 확인하고 SQL 경계만 `db` 마커로 확인한다.
7. **기본값은 `candidate_window_ms = 86400000`, `max_candidates = 5`다.** 둘 다 설정 값이라 실측 뒤 local 설정으로 조정할 수 있다.
8. **그 밖의 경계값을 확정했다.** `now`는 호출자가 넘기고, 잘못된 설정은 `ConfigError`, 공용 등급은 다른 등급보다 우선하며 결과는 frozen dataclass다. `verdict`가 null이면 근거 0건으로 계속하고 계약 샘플은 기존 검증 흐름을 재사용한다.

## 바뀐 점
