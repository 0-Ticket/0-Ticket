---
issue: 224
date: 2026-11-05
owner: Pandyo
supersedes: []
---

# L3 실제 모델 확인: Foundry 연결, 헌팅 실측, 코어 보완

## 목표

#223의 가설 생성·검증을 실제 모델(Azure Foundry `gpt-oss-120b`)로 돌려 턴·도구 호출·토큰·시간·비용과 두 출력 계약(`hunt_hypotheses`, `hunt_verification`) 통과 여부를 표로 남긴다. 검증 run이 조회할 근거를 넣는 개발용 시드 명령을 만든다. 실측에서 나온 문제를 정리한다.

- 400 `tool_use_failed`: Foundry에서 재현될 때만 고친다
- boannews 수집 실패: 원인이 L3 코드일 때만 고친다
- `config/local.toml`이 있으면 실패하는 테스트: 고친다

## 방법

### 일을 나누는 방식

- **세션(AI)**: 코드·테스트·기록, `dev-seed` 개발과 확인, Foundry에 닿는지 확인(키 없이 요청해 401을 받는 것까지. 모델 호출은 하지 않는다)
- **사람(맥)**: 실제 모델 실측, 400 재현, boannews 재현을 하고 수치를 붙여 준다. AI는 받은 수치를 `docs/notes/`에 표로 정리한다

### 1. Foundry 확인 결과 (사람이 확인함)

`docs/notes/`에 값만 적는다. 리소스 이름·주소·키는 적지 않는다.

- `gpt-oss-120b`(OpenAI, Sold by Azure), 버전 4, Global Standard, 리전 West US 3
- TPM/RPM: 실제 할당량 미확인(참고치 500만/5천). 실측 중 429가 났는지 함께 적는다
- 단가: 입력·출력 1M 토큰당 $0.15 / $0.60. 무료 크레딧(약 26.7만 원)은 적용 여부 미확인
- 계획 전 사용량: 27회 호출, 약 9.21만 토큰, 예상 비용 약 25원
- `strict`: 켜면 최종 답(content)이 빈 문자열로 온다. strict를 끄거나 도구가 없으면 정상이고, 추론 강도·출력 상한과는 관계없다. "빈 응답으로 거부, 사람이 확인함"으로 적고 확인 호출은 하지 않는다. 실측은 `strict_mode = false`로 한다
- **빈 응답 증상은 코어를 고치지 않는다.** notes에 적고 코어 담당(#209·#210·#211) 안건으로 올린다(기본값 `strict_mode = true`를 바꿀지, 빈 content를 어떻게 다룰지). PR 본문에도 적는다

### 2. 개발용 시드 (`uv run python -m soc.l3 dev-seed`)

- `soc.l3` 명령에 `dev-seed` 하위 명령을 더한다. 도움말과 출력에 "개발 DB 전용"을 적는다. DB는 `DATABASE_URL`만 쓰고 마이그레이션은 하지 않는다
  - `dev-seed`: 시드 행을 지우고(아래 지우기와 같은 규칙) 새로 넣는다. 반복 실측 때마다 `pending` Hunt 2개로 다시 시작하기 위해서다
  - `dev-seed --remove`: 지우기만 한다
- 샘플은 `tests/fixtures/l3_hunt/`에 손으로 만든 JSON 하나다. 시나리오는 두 개다
  - **위협 있음**: 가설과 맞는 Alert·Event(근거)가 있다
  - **위협 없음**: 가설에 맞는 레코드가 없다
  - IP는 `192.0.2.0/24`·`198.51.100.0/24`·`203.0.113.0/24`, 도메인은 `example.com`, 계정은 가짜 이름이다
- **시각**: 샘플에는 기준 시각과의 차이(ms)만 두고, 넣을 때의 "지금"에서 빼서 넣는다. 검증 run은 지금부터 `lookback_days`(7)일 안만 조회하기 때문이다
- **ID**: 넣을 때마다 `new_id`로 새로 만든다. 출력에는 건수와 시드 Hunt ID 두 개만 낸다. Agent Log를 Hunt별로 찾기 위해서다. 가설 등 본문은 출력하지 않는다
- **표시**
  - Alert·Event·Hunt: `details.dev_seed = true`
  - RawRecord: `siem_profile = "dev-seed"`(`details` 칸이 없다)
- **지우기**: 한 트랜잭션에서 이 순서로 지운다
  1. 시드 Hunt의 `hunt_id`를 가진 Ticket
  2. 시드 Hunt
  3. 시드 Alert·Event
  4. 시드 RawRecord
  - Agent Log는 실측 원본이라 지우지 않는다
  - 시드 Ticket이 Incident의 `ticket_ids`에 들어 있으면 아무것도 지우지 않고 멈춘다(종료 코드 1, 건수만 출력)
- 넣는 Alert·Event·Hunt는 `validate_contract`를 거친다

### 3. 실측 (사람이 맥에서 함)

- 맥의 `config/local.toml`(커밋 안 함)
  - `[llm]`: Foundry 주소·배포 이름, `strict_mode = false`
  - `[tools.allowed] l3`: 내부 DB 도구 5개(`get_alert`, `get_event`, `query_records`, `query_http_flow`, `summarize_http_flow`)로 줄인다. ELK가 없는 환경에서 SIEM 도구가 `unavailable`로 턴만 쓰는 것을 막기 위해서다. 이 사실을 notes에 적는다
- 순서: `dev-seed` → `uv run python -m soc.l3 hunt`를 3회 반복한다. 한 번에 가설 생성 1 + 새 가설 검증 최대 1 + 시드 검증 2로 최대 4 run, 모두 합해 최대 12 run이다
- 호출 상한: 위 12 run + 400 재현 최대 3 run + `llm` 마커 테스트 1 run. 넘겨야 하면 먼저 사람에게 묻는다
- 재는 것(run별): 턴, 도구 호출 수, 입력·출력 토큰, 시간, 비용 추정(단가 × 토큰), 출력 계약 통과 여부, 실패 종류(`failure`), 가설 생성 입력 글자 수가 `max_input_chars` 안인지, 429 여부
- 집계는 `agent_logs`를 `run_id`로 묶는 SQL을 notes에 둔다. 입력·출력 본문은 꺼내지 않고 숫자 칸만 읽는다. 시드 Hunt의 최종 상태와 L3 Ticket 유무는 `hunts`·`tickets`에서 건수로 센다
- 가설 생성 run의 도구 호출 수와 2층 `l3.md` 영향을 적는다. 문제가 있으면 고치지 않고 변경 안건으로 올린다
- **L3 예산 기본값**(`[agent.l3]`): 실측에서 `budget_exceeded`가 나면 수치를 보이고 사람이 정한 뒤에만 `config/default.toml`과 문서를 함께 고친다. 나지 않으면 바꾸지 않고 수치만 적는다
- 결과 표에는 가설·이유 원문을 적지 않는다

### 4. `llm` 마커 테스트 (헌팅 1건)

- #215가 아직 시작되지 않아 기존 `llm` 마커 테스트가 없다. 헌팅용 1건만 더한다(`llm`·`db` 마커. 기본 실행과 CI에서는 돌지 않는다)
- 테스트 DB에 시드를 넣고, 운영 경로(`run_agent`)로 위협 있음 Hunt 하나를 `HuntVerifier.handle`한다
- 단언
  - Hunt가 `confirmed`·`rejected`·`inconclusive` 중 하나다(출력 계약 통과)
  - Agent Log가 `subject_id = hnt_…`로 남았다
  - 결과 값(`confirmed`인지)은 모델마다 달라 단언하지 않는다
- 키는 `LLM_API_KEY`, 설정은 `config/local.toml`, DB는 `DATABASE_URL`·`AGENT_DATABASE_URL`로만 읽는다. 사람이 맥에서 1회 돌린다
- #215는 이 기록을 참조한다

### 5. 400 `tool_use_failed`

- 사람이 맥에서 실측하는 동안 같은 검증 run이 Foundry에서 400으로 실패하는지 본다. 기록은 오류 종류·HTTP 상태·오류 코드만이고, 응답 본문(모델이 만든 문자열)은 남기지 않는다
- **Foundry에서 재현되지 않으면** 코어를 고치지 않는다. notes에 적는다
  - "Groq에서만 났고 Foundry에서 재현되지 않음"
  - 지금 규칙: 400 → `provider_error`, 재시도 없음, Hunt는 `attempts`만 오르고 `max_attempts`에 이르면 `failed`
- **재현되면** 멈추고 원인과 수정안을 사람에게 보인다. 확정을 받은 뒤 고치고 이 계획의 "바뀐 점"에 적는다
- 어느 쪽이든 새 `failure` 값은 만들지 않는다(`FAILURES`는 L1·L2도 읽는다). 제공자별 분기도 만들지 않는다(`soc.agent.llm` 원칙, #210)

### 6. boannews 수집 실패

- 사람이 맥에서 `uv run python -m soc.l3.intel`을 여러 번 돌리고, 같은 주소를 curl로 받은 결과와 비교한다
- `fetch.py`는 연결 오류를 모두 `network` 하나로 묶는다. 그래서 AI가 커밋하지 않는 진단 스크립트를 준다. 스크립트는 예외 종류, HTTP 상태, `Content-Encoding`·`Content-Length` 헤더, 받은 바이트 수만 출력하고 본문은 출력하지 않는다
- 원인이 `soc.l3.intel` 코드면 고치고 테스트를 더한다(이 경우 고칠 방법을 먼저 사람에게 보인다). 환경이나 일시 실패면 재현 결과만 적는다
- 수집이 실패해도 헌팅이 계속되는 동작(#223)은 그대로 둔다

### 7. 테스트 수정

- 기본값을 검사하는 테스트가 저장소 `config/`(`default.toml` + `local.toml`)를 읽어서, `local.toml`이 있으면 실패한다. 임시 폴더에 `default.toml`만 복사해 읽게 바꾼다. 검사 내용은 그대로 두고, 테스트를 지우거나 건너뛰지 않는다
  - `tests/test_agent_config.py`: `REPO_CONFIG`를 `load_config`로 읽는 3건(코어 담당 테스트. PR 본문으로 알린다)
  - `tests/test_l3_config.py`: 기본값 검사와 `valid_l3()`
  - `tests/test_l3_hunt.py`: `test_default_config_has_hunt_settings`
- 임시 폴더를 만드는 도우미는 `tests/conftest.py`의 fixture 하나로 둔다
- `tests/test_l2_config.py`는 고치지 않는다. 같은 문제가 있다는 것만 notes에 적고 L2 담당이 정한다(이번 실측 `local.toml`은 `[l2]`를 건드리지 않는다)
- `elk`·`ssh` 마커 테스트는 일부러 `local.toml`을 읽으므로 그대로 둔다

### 순서

샘플(`tests/fixtures/l3_hunt/`) → 시드 테스트(`db`) → `dev-seed` → 테스트 수정 → `llm` 마커 테스트 → 진단 스크립트·집계 SQL 전달 → (사람 실측) → notes 정리.

## 바꿀 곳

- `src/soc/l3/__main__.py`: `dev-seed`(`--remove`) 하위 명령
- `src/soc/l3/hunt/dev_seed.py`(새 파일): 시드 넣기·지우기
- `tests/fixtures/l3_hunt/dev_seed.json`(새 파일): 두 시나리오 샘플
- `tests/test_l3_dev_seed_db.py`(새 파일, `db`): 넣기·다시 넣기·지우기·Incident에 붙었을 때 멈춤·시각 이동·시드가 아닌 행 보존
- `tests/test_l3_hunt_llm.py`(새 파일, `llm`·`db`): 실제 모델 검증 1건
- `tests/conftest.py`: 기본 설정만 담은 임시 폴더 fixture
- `tests/test_agent_config.py`, `tests/test_l3_config.py`, `tests/test_l3_hunt.py`: 기본값 검사를 임시 폴더로
- `docs/notes/224-l3-real-model.md`: Foundry 확인 결과, 실측 표, strict 빈 응답, 400·boannews 재현 결과, 집계 SQL, L2 테스트 메모
- (원인이 L3 코드일 때만) `src/soc/l3/intel/`

## 다른 코드와 맞물리는 곳

- **코어 담당 테스트(`tests/test_agent_config.py`)를 고친다.** 읽는 설정 위치만 바뀌고 검사 내용은 같다. PR 본문으로 코어 담당에게 알린다.
- **코어 코드(`src/soc/agent/`, `src/soc/tools/`)는 바꾸지 않는다.** 400이 Foundry에서 재현되면 그때 다시 확정받는다.
- **strict 빈 응답은 코어 담당 안건이다.** 기본값 `strict_mode = true`와 Foundry가 맞지 않는다. 바꿀지는 코어 담당이 정한다.
- **명령 `python -m soc.l3 dev-seed`가 새로 생긴다.** 개발 전용이고, 다른 코드는 부르지 않는다.
- **`tests/conftest.py`에 fixture 하나가 늘어난다.** 기존 fixture는 바꾸지 않는다.
- 테이블·계약·설정 키는 바꾸지 않는다. 마이그레이션은 없다.
- **#215**: `llm` 마커 테스트와 Foundry 확인 결과를 이 이슈가 먼저 기록한다. #215는 그 기록을 참조한다.

## 범위 밖

- 실행기 등록, 주기 실행
- ELK 실데이터 실측(#218, #234 이후)
- 가설 생성 run의 도구 제한, 2층 `l3.md` 분리(실측 뒤 안건으로만 올림)
- 조회 API(#239), Hunt 계약 변경
- strict 빈 응답 수정(코어 담당 안건)
- `tests/test_l2_config.py` 수정(L2 담당)
- Groq에서 400 재현(지금 키는 Azure 키다)

## 완료 기준

- [ ] Foundry 확인 결과(Sold by Azure, 버전, 배포 유형, 리전, TPM 미확인, 단가)와 strict 결과("빈 응답으로 거부, 사람이 확인함")가 `docs/notes/`에 있다. 키·리소스 이름·주소는 없다
- [ ] strict 빈 응답이 코어 담당 안건으로 notes와 PR 본문에 있다
- [ ] `dev-seed`로 위협 있음·없음 Hunt 2개(`pending`)와 근거 Alert·Event가 개발 DB에 들어간다. 시각은 넣은 시점 기준 `lookback_days` 안이다
- [ ] `dev-seed`를 다시 돌리면 이전 시드 행이 지워지고 새로 들어간다. `--remove`는 시드 행만 지우고, 시드가 아닌 행과 Agent Log는 남긴다. 시드 Ticket이 Incident에 붙어 있으면 아무것도 지우지 않는다
- [ ] 실제 모델 가설 생성 run: 출력 계약 통과 횟수와 실패 종류를 적었다
- [ ] 실제 모델 검증 run: 위협 있음 시나리오의 `confirmed`·L3 Ticket 횟수, 없음 시나리오의 `rejected` 횟수(그 밖의 결과 포함)를 적었다
- [ ] 턴·도구 호출·토큰·시간·비용 추정·429 여부를 run별 표로 적었다
- [ ] 가설 생성 run의 L3 도구 사용 여부와 2층 `l3.md` 영향을 적었다(필요하면 변경 안건)
- [ ] L3 예산을 바꿨으면 사람이 정했고, `config/default.toml`과 문서를 함께 고쳤다
- [ ] 400 `tool_use_failed`의 Foundry 재현 결과를 적었다. 재현되지 않았으면 지금 실패 종류와 재시도 규칙이 적혀 있다. 재현됐으면 확정받은 수정 뒤 같은 검증 run이 실패하지 않는다
- [ ] boannews 재현 결과(재현됨/안 됨, 원인)를 적었고, L3 코드 원인이면 고쳤다
- [ ] `llm` 마커 테스트 1건이 있고, 사람이 1회 돌린 결과가 notes에 있다
- [ ] `config/local.toml`(LLM 설정, `[tools.allowed] l3` 축소 포함)이 있어도 `uv run pytest`가 통과한다
- [ ] 코어 테스트 수정과 strict 안건을 PR 본문으로 코어 담당에게 알렸다
- [ ] 키·비밀 값·리소스 이름이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m db` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

1. **시드는 `soc.l3`의 `dev-seed` 하위 명령이다.** 매번 지우고 다시 넣는다. `db` 마커 테스트로 확인할 수 있고, 반복 실측마다 `pending` Hunt로 다시 시작하기 위해서다. 시각은 넣는 시점 기준으로 옮긴다(검증 조회 기간이 7일이라서). RawRecord에는 `details`가 없어 `siem_profile`로 표시한다. Agent Log는 실측 원본이라 지우지 않는다.
2. **실측 횟수는 `soc.l3 hunt` 3회(최대 12 run)다.** 400 재현 최대 3 run, `llm` 테스트 1 run을 더해 상한으로 둔다. 비용 때문이다. 넘겨야 하면 먼저 묻는다.
3. **400이 Foundry에서 재현되지 않으면 코어를 고치지 않는다.** 이슈는 코어 수정을 전제했다. 하지만 지금 키는 Azure 키라 Groq에서 재현할 수 없다. 그리고 `tool_use_failed`만 보고 재시도하면 #210이 피한 제공자별 분기가 생긴다. 재현되면 원인을 보고 다시 확정받는다. 새 `failure` 값은 만들지 않는다.
4. **테스트 수정 범위는 코어와 L3 테스트 3개 파일이다.** 이슈는 `test_agent_config.py` 1건만 들었다. 그런데 같은 파일의 3건, 그리고 L3 테스트(`test_l3_config.py`, `test_l3_hunt.py`)도 `local.toml`을 읽어 실측 설정으로 실패한다. `test_l2_config.py`도 같은 모양이지만 이번 `local.toml`은 `[l2]`를 건드리지 않는다. 다른 담당의 테스트라서 기록만 하고 L2 담당이 정한다.
5. **실측 때 L3 도구는 내부 DB 도구 5개로 줄인다**(`local.toml`, 커밋 안 함). ELK 없는 환경에서 SIEM 도구가 턴만 쓰는 것을 막기 위해서다.
6. **실측과 boannews 재현은 사람이 맥에서 한다.** 세션은 코드·테스트·기록·`dev-seed`를 맡는다. 세션의 바깥 연결은 프록시를 거쳐 boannews 재현 조건이 다르기 때문이다. 세션에서 Foundry에 닿는지는 키 없이 확인했다(401).
7. **TPM은 "미확인(참고치 500만/5천)"으로 기록한다.** 실제 할당량을 확인하지 못했다. 실측 중 429 여부를 함께 적는다.
8. **strict는 확인 호출 없이 "빈 응답으로 거부, 사람이 확인함"으로 기록한다.** 사람이 Foundry에서 strict를 켜면 최종 content가 빈 문자열로 오는 것을 확인했다. 이 증상은 코어를 고치지 않고 코어 담당 안건으로 올린다. 실측은 `strict_mode = false`로 한다.
9. **브랜치는 `feat/224-l3-real-model`이고 push하지 않는다**(`AGENTS.md`).

## 바뀐 점
