---
issue: 223
date: 2026-11-04
owner: Pandyo
supersedes: []
---

# L3 가설 헌팅: 가설 생성·검증·L2 투입 (가짜 모델)

## 목표

`uv run python -m soc.l3 hunt` 한 번으로 뉴스 수집 → 가설 생성 run → `pending` Hunt 검증 run을 차례로 돌리고, 위협이 확인되면 L3 Ticket을 만들어 L2로 넘긴다. 저장 규칙과 상태 전이는 모델과 상관없으므로, 실행 함수를 주입해 가짜 실행 결과와 `run_task`(+가짜 모델·가짜 도구)로 흐름 전체를 테스트한다. 실행기 등록, 주기 실행, 실제 모델 확인은 후속 이슈에서 한다.

## 방법

### 1. 설정 (`config/default.toml`의 `[l3.hunt]`)

#221의 L3 로더(`soc.l3.config.load_config`)로 읽는다. 기본값과 설명을 `config/default.toml`에 둔다.

| 키 | 기본값 | 뜻 |
|---|---|---|
| `collect_before` | `true` | 헌팅 전에 `soc.l3.intel` 수집을 한 번 돌린다 |
| `news_window_days` | `3` | 가설 생성 입력 뉴스 기간(일) |
| `news_limit` | `5` | 가설 생성 입력 뉴스 최대 건수 |
| `case_limit` | `3` | 가설 생성 입력 Case 최대 건수 |
| `max_hypotheses` | `1` | 만들 가설 수 |
| `lookback_days` | `7` | 검증 run의 조회 기간(일) |
| `confirm_threshold` | `0.7` | `confirmed`로 저장하는 최소 확신도 |
| `max_attempts` | `2` | 검증 run 시도 한도 |

설정이 틀리면 `ConfigError`로 멈춘다(종료 코드 2).

### 2. 출력 계약 (`contracts/`)

`AgentTask.output_contract`는 `soc.contracts.CONTRACT_NAMES`의 이름만 받으므로 두 계약을 `contracts/`에 새로 두고 `validate.py`에 등록하고 Python 생성 코드를 만든다. L3 내부 출력 계약이고 다른 단계는 읽지 않는다. 실제 모델이 붙은 뒤에도 그대로 쓰는 영구 계약이다. 최상위는 `additionalProperties: false`, 모든 필드 필수다.

**`hunt_hypotheses`** (가설 생성 run 출력)

| 필드 | 타입 | 설명 |
|---|---|---|
| `hypotheses` | 객체 목록(빈 목록 가능) | 가설 목록 |
| `hypotheses[].hypothesis` | 문자열(빈 값 불가) | 가설 문장 |
| `hypotheses[].attack_techniques` | 문자열 목록, 1개 이상, 중복 없음 | ATT&CK 기법 ID(`^T[0-9]{4}(\.[0-9]{3})?$`) |
| `hypotheses[].news_ids` | 1 이상 정수 목록, 중복 없음 | 참고한 `threat_news.id` |
| `hypotheses[].case_ids` | `case_id` 목록, 중복 없음 | 참고한 Case ID |

**`hunt_verification`** (검증 run 출력)

| 필드 | 타입 | 설명 |
|---|---|---|
| `result` | `confirmed` / `rejected` / `inconclusive` | 검증 결과 |
| `confidence` | 숫자 0~1 | 확신도 |
| `reason` | 문자열(빈 값 불가) | 이유 |
| `evidence_ids` | `evidence_id` 목록, 중복 없음 | 근거 ID |
| `entities` | Entity 목록 | 모델이 확인한 엔티티 |

조건부 규칙은 두지 않는다. 결과를 낮추는 규칙은 코드가 적용한다(5절).

`cited_ids`: 가설 생성은 빈 목록(뉴스·Case 참조는 근거 ID가 아니고 코드가 입력과 대조한다), 검증은 `evidence_ids`.

### 3. 실행 함수 주입

가설 생성과 검증 워커는 실행 함수 `run: Callable[[AgentTask], AgentResult]`를 받는다. 기본값은 `run_agent`다. 테스트는 두 가지를 넣는다.

- 가짜 실행 결과: `AgentResult`를 바로 돌려준다. 상태 전이, Ticket, 결과 낮추기, 엔티티 모으기를 확인한다
- `run_task` + 가짜 모델(`tests/fake_model.py`) + 가짜 도구 + 메모리 기록기: Agent Log, `data` 주입, 실패 경로를 확인한다. 설정은 `soc.agent.config.load_config()`로 읽는다(#210이 머지되면 늘어나는 키를 손으로 맞추지 않기 위해)

도구 결과의 `alt_`·`evt_`를 근거 장부에 넣는 일은 #211이 하므로, 그전까지 `run_task` 경로에서 `alt_`·`evt_`를 인용하면 `evidence_id_error`다. 이것은 정상 동작으로 보고 실패 경로 테스트로 쓴다.

### 4. 가설 생성 run (`src/soc/l3/hunt/`)

1. 설정 버전(`[l3.intel.attack] version`)의 `attack_techniques` 행이 없으면 run을 하지 않고 "ATT&CK 버전 없음"을 출력한다(LLM 호출 낭비 방지).
2. `new_id("hrn")`으로 헌팅 실행 ID를 만든다.
3. 입력(`AgentTask.data`)
   - `news`: `COALESCE(published_at, fetched_at)`이 최근 `news_window_days`일 안인 `threat_news`를 그 값 내림차순(같으면 `id` 내림차순)으로 최대 `news_limit`건. 항목마다 `id`, `source`, `title`, `summary`, `published_at`(epoch ms 또는 null)
   - `cases`: `confirmed_at` 내림차순으로 최대 `case_limit`건(상태 무관). 항목마다 `id`, `title`, `summary`, `severity`, `entities`
   - `max_hypotheses`
4. `AgentTask(stage="l3", task="l3_hypothesize", output_contract="hunt_hypotheses", subject_type="hunt", subject_id=<hrn_>, allowed_evidence_ids=())`
5. 코드 검사
   - 앞에서부터 `max_hypotheses`개만 쓰고 나머지는 버린 건수만 센다
   - 기법 ID 중 하나라도 설정 버전의 `attack_techniques`에 없으면 그 가설은 저장하지 않고 건수만 센다
   - 입력에 없던 뉴스 `id`·Case ID는 그 참조만 버린다
6. 저장: 가설마다 Hunt(`status = pending`, `attempts = 0`, `confidence`·`reason`·`verified_at` null, `evidence_ids = []`, `entities = []`, 같은 `hunt_run_id`). 쓰기 전에 `validate_contract("hunt", …)`. 한 run의 Hunt는 한 트랜잭션으로 쓴다.
7. `details.sources = {"news": [{"id", "source", "title", "summary", "published_at"}], "case_ids": [...]}`. 뉴스는 다시 받으면 내용이 바뀌므로(#221) 그 시점의 제목·요약을 복사한다.
8. 실패(`ok = False`)하면 Hunt를 만들지 않고 실패 종류만 출력한다.
9. 뉴스 재사용은 막지 않는다.

### 5. 검증 run (워커)

워커 클래스는 #215 설계의 모양(`stage = "l3"`, `name`, `poll(limit)`, `handle(subject_id)`)으로 만든다. 실행기 등록은 후속 이슈에서 한다.

- `poll(limit)`: `pending`인 Hunt ID를 `created_at`, `id` 순으로 최대 `limit`개
- `handle(hunt_id)`
  1. Hunt를 읽는다. 없거나 `pending`이 아니면 아무것도 하지 않고 끝낸다(멱등)
  2. 입력(`data`): `hypothesis`, `attack_techniques`(`[{"id", "name"}]`, 이름은 설정 버전의 `attack_techniques`에서, 없으면 null), `window`(`{"from", "to"}` epoch ms, `handle`을 부른 시각부터 `lookback_days`일 전까지)
  3. `AgentTask(stage="l3", task="l3_verify", output_contract="hunt_verification", subject_type="hunt", subject_id=<hnt_>, attempt=<attempts + 1>)`. 모델 실행은 DB 트랜잭션 밖에서 한다
  4. 결과 처리(아래)를 한 트랜잭션으로 쓴다. Hunt 갱신은 `WHERE id = … AND status = 'pending' AND attempts = <읽은 값>` 조건이고, 0행이면 다른 실행이 먼저 처리한 것으로 보고 Ticket을 만들지 않는다
- 도구: 운영에서는 L3 허용 도구(#211~#213), 이 이슈의 테스트는 `run_task`의 `tools`로 가짜 도구를 넣는다

**결과를 낮추는 규칙** (낮췄으면 `details.downgraded = {"from": <원래 결과>, "rules": [...]}`)

- `confirmed`인데 확신도가 `confirm_threshold` 미만(`threshold`) 또는 `alt_`·`evt_` 근거 없음(`no_record_evidence`) → `inconclusive`
- `rejected`인데 근거 없음(`no_evidence`) → `inconclusive`

**엔티티**

- 근거 ID 중 `alt_`는 `alerts.entities`, `evt_`는 `events.entities`를 읽어 모은다. 행이 없는 ID는 건너뛰고 건수를 `details.missing_evidence_rows`에 남긴다
- 레코드 엔티티 뒤에 모델 엔티티를 붙여 중복을 지운다(`type`·`value`·`role`이 모두 같으면 같은 엔티티)
- 레코드에 없고 모델만 낸 엔티티는 `details.model_only_entities`에 따로 남긴다
- 결과가 무엇이든 Hunt `entities`는 이 값이다

**성공** (`ok = True`): `status = <결과>`, `confidence`, `reason`, `evidence_ids`, `entities`, `attempts + 1`, `verified_at = updated_at = 지금`. `validate_contract("hunt", …)`를 거친다.

**위협 발견 → L2 투입**: `confirmed`이면 같은 트랜잭션에서 Hunt를 먼저 갱신하고 Ticket을 만든다: `id = new_id("tkt")`, `origin = l3`, `status = escalated`, `alert_ids = []`, `hunt_id`, `entities` = Hunt의 엔티티, `verdict = null`, `details = {}`. `validate_contract("ticket", …)`를 거친다. Ticket INSERT는 savepoint 안에서 하고, `UniqueViolation`(`tickets_hunt_id_key`)이면 "이미 만든 Ticket"으로 다룬다.

**실패** (`ok = False`, `log_error` 포함): `attempts + 1`, `details.verify_failures`에 `{"attempt", "failure", "run_id"}`를 더한다. `attempts`가 `max_attempts`에 이르면 `failed`(`confidence`·`reason`·`verified_at` null), 아니면 `pending`.

### 6. 명령 (`uv run python -m soc.l3 hunt`)

1. `collect_before`가 참이면 `soc.l3.intel`의 수집을 한 번 돌리고 출처별 결과 줄(`format_results`)을 출력한다. 실패한 출처가 있어도 계속한다. 수집 실패는 종료 코드에 영향을 주지 않는다
2. 가설 생성 run 1회. 출력: 저장한 가설 수, 기법 없음으로 버린 수, 한도 초과로 버린 수, 실패 종류
3. 가설 생성이 실패해도 `pending`인 Hunt 전부(방금 만든 것과 재시도 대기)를 검증한다
4. 끝나면 이번 실행에서 다룬 Hunt의 상태별 건수를 출력한다. 가설·이유·뉴스 같은 본문은 출력하지 않는다

- DB 주소는 `DATABASE_URL`. 마이그레이션은 하지 않는다
- 종료 코드: 0 정상(가설 0건, 일부 Hunt `failed` 포함), 1 가설 생성 run 실패 또는 DB 오류, 2 설정 오류(`DATABASE_URL` 없음 포함). DB 오류는 예외 종류만 출력한다
- 운영 경로(`run_agent`)라 #210 머지 전에는 가설 생성이 `provider_error`로 끝난다

### 7. 프롬프트와 밖에서 온 문자열

- 4층 작업 프롬프트 두 개: `src/soc/l3/prompts/l3_hypothesize.md`, `src/soc/l3/prompts/l3_verify.md`. `TaskPrompt.version`은 파일 내용의 sha256. #210의 금지 문구(`FORBIDDEN_PHRASES`: "이전 지시", "대응을 실행" 등)를 쓰지 않는다
- 2층 `l3.md`는 #210이 쓰고 이 이슈 담당이 리뷰한다. 검증용 문장("가설 → 집계 → 레코드")이 가설 생성 run에도 붙으므로 그 점을 리뷰에서 본다
- 뉴스 제목·요약, Case 제목·요약·엔티티, 가설 문장은 `data`로만 넘긴다(구분자 안, #209)
- Hunt의 `hypothesis`·`reason`·모델 엔티티는 밖에서 온 문자열에서 나온 LLM 출력이다(#217). 로그와 명령 출력에 본문을 남기지 않는다

### 순서

샘플(`tests/fixtures/`) → 테스트 → 출력 계약·생성 코드 → 설정 → 가설 생성 → 검증 워커 → 명령 → 프롬프트.

## 바꿀 곳

- `contracts/hunt_hypotheses.schema.json`, `contracts/hunt_verification.schema.json`: 새 파일
- `src/soc/contracts/generated/`: 다시 생성
- `src/soc/contracts/validate.py`: 두 계약 등록
- `tests/contract_samples.py`: `CONTRACT_NAMES`에 두 이름
- `tests/fixtures/contracts/valid|invalid/hunt_hypotheses.json`, `hunt_verification.json`: 새 샘플
- `config/default.toml`: `[l3.hunt]`
- `src/soc/l3/__main__.py`: `hunt` 명령
- `src/soc/l3/hunt/`: 설정 읽기, 가설 생성, 검증 워커, 저장
- `src/soc/l3/prompts/l3_hypothesize.md`, `l3_verify.md`: 4층 프롬프트
- `tests/fixtures/l3_hunt/`: 손으로 만든 뉴스(지시문을 넣은 제목 포함)·Case·Alert·Event·raw_record·가짜 모델 시나리오
- `tests/`: 가설 생성·검증·명령 테스트(DB가 필요한 것은 `db` 마커)
- `docs/notes/223-threat-hunt.md`: 개발 기록

## 다른 코드와 맞물리는 곳

- **`CONTRACT_NAMES`에 `hunt_hypotheses`, `hunt_verification`이 늘어난다.** 기존 계약의 모양은 바뀌지 않는다. 계약 모듈(#192) 담당 승인을 받고 다른 담당에게 PR로 알린다.
- **L3 Ticket(`origin = l3`)을 처음 만든다.** `status = escalated`인데 `verdict = null`이고 `alert_ids = []`다. L2 코드는 `escalated` Ticket에 `verdict`가 있다고 가정하면 안 되고, `hunt_id`로 Hunt를 찾아 `evidence_ids`를 따라간다. L2 담당에게 알린다.
- **`hunts`·`tickets`(쓰기), `cases`·`alerts`·`events`·`threat_news`·`attack_techniques`(읽기).** 테이블은 바꾸지 않는다. 마이그레이션은 없다.
- **#210(머지 전)**: `TaskPrompt` 금지 문구, `run_task`의 새 설정 키. 테스트 설정은 `load_config()`로 읽는다. 먼저 머지되는 쪽에 맞춰 rebase한다.
- **#215**: 워커 모양을 맞춘다. `AgentWorker` Protocol은 아직 없어 상속하지 않는다.
- **설정 키 `[l3.hunt]`**가 새로 생긴다.
- **명령 `python -m soc.l3`**가 새로 생긴다. `python -m soc.l3.intel`은 그대로다.

## 범위 밖

- 실행기 등록, 주기 실행(L3 실행 방식, D-030은 정하지 않는다), 실제 모델 확인(#210, #211~#213, #215 뒤 후속 이슈)
- 도구 결과의 `alt_`·`evt_`를 근거 장부에 넣는 것(#211)
- 2층 `l3.md` 작성(#210)
- 뉴스·Case 재사용 제한, 오래된 Hunt 정리

## 완료 기준

- [ ] 가설 생성(가짜 실행 결과) → `pending` Hunt가 같은 `hunt_run_id`로 저장되고, `details.sources`에 뉴스 `id`와 그 시점의 제목·요약이 있다
- [ ] 설정 버전의 `attack_techniques`에 없는 기법 ID(`T9999` 등)를 낸 가설은 저장되지 않는다. `max_hypotheses`를 넘는 가설은 저장되지 않는다. 입력에 없던 뉴스·Case 참조는 버려진다
- [ ] 설정 버전의 ATT&CK이 DB에 없으면 가설 생성 run을 하지 않는다
- [ ] `published_at`이 null인 뉴스는 `fetched_at`으로 기간에 들어간다
- [ ] 검증(가짜 실행 결과): `confirmed` → Hunt `confirmed` + L3 Ticket(`origin = l3`, `status = escalated`, `alert_ids = []`, `hunt_id`, `verdict = null`), `rejected`·`inconclusive` → Ticket 없음
- [ ] 확신도 임계값 미만이거나 `alt_`·`evt_` 근거가 없는 `confirmed`, 근거가 없는 `rejected`는 `inconclusive`로 저장되고 `details.downgraded`가 남는다
- [ ] Hunt·Ticket `entities`가 인용된 Alert·Event 엔티티와 모델 엔티티를 중복 없이 합친 값이고, 모델만 낸 엔티티가 `details.model_only_entities`에 있다
- [ ] 검증 실패 → `attempts` 증가·`pending` 유지·`details.verify_failures` 추가, 한도에 이르면 `failed`
- [ ] `run_task` 경로: 도구 결과의 `alt_`를 인용하면 `evidence_id_error`로 실패 처리되고, `agl_`만 인용한 `confirmed`는 `inconclusive`가 된다
- [ ] 같은 Hunt로 `handle`을 두 번 불러도 Ticket은 하나이고, 두 번째는 실행 함수를 부르지 않는다
- [ ] 수집 실패가 헌팅을 멈추지 않고, `collect_before = false`면 수집하지 않는다
- [ ] 가설 생성 run이 실패해도 재시도 대기 Hunt를 검증하고 종료 코드는 1이다. 설정 오류는 2, 정상은 0이다
- [ ] 명령 출력에 가설·이유·뉴스 본문이 나오지 않는다
- [ ] 뉴스 제목에 지시문을 넣은 샘플이 프롬프트(system)가 아니라 `data`에만 들어간다
- [ ] 가설 생성·검증 run의 Agent Log가 `subject_type = hunt`, `subject_id`는 각각 `hrn_`·`hnt_`로 남는다
- [ ] 저장하는 Hunt·Ticket이 모두 `validate_contract`를 거친다
- [ ] 두 출력 계약의 올바른·틀린 샘플 테스트가 있고 생성 코드 차이 검사(`--check`)가 통과한다
- [ ] 출력 계약 추가를 L3 담당과 계약 모듈 담당이 승인하고, 다른 담당에게 PR로 알린다
- [ ] DB 테스트는 `db` 마커로 나눈다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과(`db` 마커 테스트도 실행)
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

1. **`confirmed` 경로는 실행 함수 주입과 가짜 실행 결과로 테스트한다.** 지금 `run_task`의 근거 장부에는 도구 결과의 `alt_`·`evt_`가 들어가지 않아(#211이 함) `run_task` 경로로는 `confirmed`를 만들 수 없다. 이슈의 "가짜 모델로 검증: `confirmed` → Ticket"을 "가짜 실행 결과로"로 바꾸고, `run_task` 경로는 Agent Log·`data`·실패 경로 확인에 쓴다. #209 코드를 바꾸지 않는다.
2. **출력 계약 `hunt_hypotheses`·`hunt_verification`을 `contracts/`에 둔다.** 승인은 L3 담당과 계약 모듈 담당이 PR에서 한다. 기존 계약 모양이 바뀌지 않고 다른 단계가 읽지 않는 L3 내부 계약이라서다. 가짜 모델 검증이 끝나도 실제 모델 출력 검사에 그대로 쓴다.
3. **근거 없는 `rejected`도 `inconclusive`로 낮춘다.** 이슈에는 `confirmed` 규칙만 있었지만 Hunt 계약은 `rejected`에도 근거 1개 이상을 요구한다(#217). 낮추는 규칙을 코드 한 곳에 모은다.
4. **가설 생성 출력에 엔티티를 두지 않고 검증 입력에서 뺀다.** 이슈의 검증 입력 "엔티티"는 출처가 없었다. `pending` Hunt는 `entities = []`다.
5. **Case 입력에 `id`를 넣는다.** 출력이 참고한 Case ID를 내야 하기 때문이다.
6. **`published_at`이 null인 뉴스는 `fetched_at`으로 기간·정렬에 넣는다.**
7. **`lookback_days` 기본값은 7, 조회 기간은 `{"from", "to"}` epoch ms로 넘긴다.**
8. **가설 생성 run이 실패해도 재시도 대기 Hunt 검증은 계속한다.** 종료 코드 0 정상, 1 가설 생성 실패·DB 오류, 2 설정 오류. 수집 실패는 종료 코드에 영향 없음.
9. **`max_hypotheses` 초과는 앞에서부터 N개, ATT&CK 버전이 DB에 없으면 가설 생성을 건너뜀, Hunt 갱신은 `status`·`attempts` 조건부, Ticket INSERT는 savepoint 안.** 같은 트랜잭션에서 `UniqueViolation`을 그냥 잡으면 Hunt 저장까지 롤백되기 때문이다.
10. **Hunt·Ticket 엔티티는 코드가 인용된 Alert·Event에서 모으고 모델 엔티티와 합친다.** 엔티티가 빈 L3 Ticket을 막기 위해 사람이 근거 레코드에서 채우자고 제안했다. AI는 레코드 엔티티만 쓰는 안을 추천했지만(모델 엔티티는 근거가 없고 밖에서 온 문자열일 수 있음) 사람이 합치는 안으로 정했다. 그래서 모델만 낸 엔티티를 `details.model_only_entities`에 따로 남긴다.
11. **마이그레이션은 없다.** 필요한 테이블이 모두 있다.

## 바뀐 점

- 2026-11-05 · 마무리 중 #210·#211이 main에 머지돼 최신 `origin/main`으로 rebase한다. #211로 도구 결과의 `alt_`·`evt_`가 근거 장부에 들어가므로, 완료 기준 "`run_task` 경로: 도구 결과의 `alt_`를 인용하면 `evidence_id_error`"는 "`run_task` 경로: 도구 결과의 `alt_`를 근거로 `confirmed` → L3 Ticket, 도구 결과에 없던 `alt_`를 인용하면 `evidence_id_error`"로 바꾼다. `run_task` 경로 테스트는 `ToolRegistry`·`ToolSpec`으로 가짜 도구를 넣는다. 사람이 정함
