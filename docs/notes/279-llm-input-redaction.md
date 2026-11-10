---
issue: 279
date: 2026-11-10
owner: Interludeal
plan: 279-llm-input-redaction.md
supersedes: []
---

# 외부 LLM으로 보내는 입력을 가리고, 가림 규칙의 오탐을 줄였다

## 한 일

- 모델을 부르기 직전 SDK 입력 필터(`runner._execute`의 `screen_input`, 예전 `check_budget` 자리)가 입력 항목마다 비밀 값을 `[REDACTED]`로 가린다. 대상은 `task.data`, 도구 결과, 형식 오류 재요청, 앞 모델 출력이다. 입력 예산(`max_input_chars`)은 가린 입력의 글자 수로 검사한다.
- SDK가 필터 결과를 `on_llm_start`에 넘기므로 Agent Log의 model 줄 `input`과 `records` 도구 줄 `output`이 모델이 받은 입력과 같아졌다. D-036의 "이어 붙이면 전체 입력"이 맞는 말이 됐다(테스트로 확인).
- 가림 함수는 `run_task`에서 한 번 만들어 필터와 `RowWriter`(Agent Log 쓰기 직전 가림)가 함께 쓴다. 가림이 예외를 내면 원문을 보내지 않고 `provider_error`로 끝낸다(`sent=false` 줄이 남는다).
- 규칙 변경(`redact.py`): 환경변수 값 최소 길이 4 → 8, `pwd=`는 값이 `/`로 시작하면 건너뜀, `token`·`secret`(`access_token`, `client_secret` 포함)과 `Authorization: Basic|ApiKey` 추가, 근거 ID 모양은 건드리지 않음.
- 범위·한계를 `docs/security.md` "모델 입력"에, 결정은 D-048과 D-036 메모(`docs/decisions.md`)에 적었다.

## 계획과 달라진 점

- **객체 키 이름을 늘렸다.** `_SECRET_KEYS`에 `token`·`access_token`·`refresh_token`·`secret`·`client_secret`을 더했다(계획은 "개발 때 정함"). 필터는 JSON 문자열만 보고 Agent Log 쓰기는 객체를 보는데, 두 쪽이 같은 값을 가려야 로그가 모델 입력과 맞는다.
- **JSON 문자열 속 `"키": "값"` 규칙을 더했다.** `_SECRET_KEYS`의 이름이 JSON 문자열 속에 있으면 값을 닫는 따옴표 앞까지 가린다. 도구 결과는 모델에게 JSON 문자열로 가서 객체 키 규칙이 돌지 않기 때문이다(#213 기록의 같은 문제). 이 규칙 덕에 `"authorization": "Digest ..."`처럼 `Basic`·`ApiKey`가 아닌 값도 가려진다.
- **근거 ID는 ID 모양으로 건너뛴다.** 필터는 문자열만 봐서 `id_fields`를 모른다. 접두사(`soc.ids.PREFIXES`) + UUIDv7 모양을 모든 규칙에서 제외했다. 계획에 적은 방식이다.
- **가림 함수 전달.** `_writer(sink, config, redact=None)`에 선택 인자를 더했다. `_before_start`는 인자 없이 불러 예전처럼 직접 만든다. `_execute`는 `redact` 인자를 받는다.
- **입력 항목은 dict만 온다(openai-agents 0.24.0).** 실제 SDK 실행에서 필터가 받은 항목 16개가 모두 dict였고, `RunItem.to_input_item`이 항목을 `model_dump`/dict 복사로 바꿔 `ResponseInputItemParam`(TypedDict)으로 넘긴다(`agents/items.py`). 객체가 오는 경로는 없다. `_as_json`(dict가 아니면 `jsonable`로 바꿈)은 SDK가 바뀌어 객체가 와도 가림을 건너뛰어 원문이 나가지 않게 하는 방어다. 그 경로는 실제로 만들 수 없어 `_as_json` 자체만 테스트로 고정했다(`test_sdk_input_items_are_dicts_and_objects_are_converted_not_leaked`). SDK를 올릴 때 이 테스트의 첫 단언(모두 dict)이 깨지면 가림 경로를 다시 본다.
- **페이지 이동 표지는 가리지 않는다.** `next_token`·`page_token`·`next_page_token`·`continuation_token`은 비밀이 아닌데 "이름이 `token`으로 끝나는 낱말" 규칙에 걸려 값이 가려졌다(마무리 때 샘플로 확인해 찾음). 이 이름들만 건너뛴다(`_CURSOR_NAME`). `csrf_token=` 같은 다른 `*_token`은 계속 가린다. `tokens_in`·`token_count`·`max_tokens`·`secret_santa`처럼 `token`·`secret`으로 끝나지 않는 이름과 문장 속 낱말("Invalid token provided")은 원래 걸리지 않는다(샘플로 고정).

## 다음 사람이 알아야 할 것

- **8자 미만 환경변수 비밀은 가려지지 않는다.** 개발용 `admin` 같은 키가 그렇다. 설정에 짧은 키를 쓰면 외부 LLM으로 나간다.
- **`db_password=`·`MYSQL_PASSWORD=`처럼 낱말 앞에 다른 글자가 붙은 `password`·`api_key`는 여전히 못 가린다**(`\bpassword`가 `_`와 `p` 사이에서 맞지 않음). `DB_TOKEN=`은 새 규칙으로 가려진다. `password`·`api_key`에도 같은 접두 규칙을 쓰면 되지만 이번 범위가 아니라 두었다(`security.md` 한계에 적음).
- **카멜 케이스 이름(`accessToken=`, `clientSecret=`)은 못 가린다.** 낱말 경계를 `_`·`-`로만 본다.
- **명령줄 모양(`--password 값`, `-pSECRET`)과 이름·값 쌍 헤더는 못 가린다.** SSH `processes` 점검의 위험(#213)은 그대로다.
- **`ps`·`auth_log` 같은 결과는 자른 뒤에 가린다.** 잘린 조각난 환경변수 값은 못 가린다(#213 기록과 같다).
- **가림은 판정 증거도 가린다.** 모델은 `[REDACTED]`를 본다. 실제 모델로 판정 품질이 달라지는지는 확인하지 않았다.
- **`runner.py`의 `_execute`·`_writer`는 #280과 겹친다.** 머지 순서는 담당자가 팀과 정한다.
- **D-036의 읽는 규칙은 같다.** 바뀐 것은 model 줄 `input`과 `records` 도구 줄 `output`이 가림 적용 후 값이라는 점뿐이다. 모델 출력 줄·`details`·도구 인자 줄은 쓰기 직전에만 가린다.
- 가림에 쓸 환경변수 값은 `run_task`마다 `build_redactor`가 다시 읽는다. 실행 중에 바뀐 값은 다음 run부터 반영된다.
- **이 변경과 무관한 기존 현상 두 가지.** 둘 다 `origin/main`(`d0247ac`)을 그대로 체크아웃해 `tests/test_migrate.py`와 `tests/test_tools_ssh.py`를 돌렸을 때 똑같이 나왔다(144건 통과, 1건 실패).
  - `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`: Windows가 줄바꿈이 든 파일명을 만들지 못해 `OSError`로 실패한다(#278 기록에도 있다). Linux CI에서는 돈다.
  - `tests/fake_ssh.py:107`의 `FakeSshServer._start.<locals>.silent()` 태스크가 "Task was destroyed but it is pending!" 경고를 낸다. 테스트는 통과하고 `ssh` 마커 테스트 파일(`test_tools_ssh.py`)에서 나온다. 가림과 관계없다.

## 확인 방법

- `PYTHONUTF8=1 uv run ruff format --check .`: 통과
- `PYTHONUTF8=1 uv run ruff check .`: 통과
- `PYTHONUTF8=1 uv run python scripts/generate_contracts.py --check`: 통과(계약은 바뀌지 않았다)
- `PYTHONUTF8=1 uv run pytest`: 1,435건 통과, 1건 실패(위 `test_migrate`, 변경과 무관). 최신 `origin/main`(`d0247ac`)으로 리베이스한 뒤의 코드로 돌렸다. db·qdrant·embedder·elk·ssh·llm 마커 테스트는 기본 실행에서 빠진다
- 테스트를 먼저 썼다. 구현 전에는 새 테스트 중 규칙·필터를 보는 것이 실패했다(샘플 마스킹, 최소 길이, `pwd`, ID 보존, 필터).
- 주요 테스트
  - `tests/test_agent_input_redaction.py`: 가짜 모델 입력과 Agent Log에 비밀이 없음(도구 결과 세 종류, `task.data`), 로그 model 줄을 이어 붙인 입력이 모델이 받은 입력과 같음, 여러 턴과 형식 오류 재요청에서 앞 입력이 뒤 입력의 접두이고 `input_reset`이 없음, 가림 실패 시 모델 호출 없음·`provider_error`·`sent=false` 줄, 환경변수 값이 ID 조각과 겹쳐도 ID·근거 인용 유지, 짧은 환경변수 값은 그대로, 도구 이름과 `call_id`는 그대로
  - `test_without_the_filter_the_model_would_receive_the_secrets`: 대조 시험이다. 가림 함수가 아무것도 안 가리면 같은 시나리오에서 비밀이 모델 입력에 그대로 있다. 위 테스트들이 `run_task` → `Runner.run_sync` → SDK 입력 필터 → 가짜 모델 경로를 실제로 거친다는 증거다(필터 함수를 직접 부르는 테스트는 없다)
  - `test_normal_fields_reach_the_model_unchanged`: `next_token`, `tokens_in`, `PWD=/home/alice`가 SDK 경로로 모델에 그대로 간다
  - `tests/test_agent_redact.py`: 샘플(`tests/fixtures/agent/redact_samples.json`)의 정상 문자열 불변(`next_token` 등 페이지 이동 표지, `tokens_in`·`token_count`·`max_tokens`·`secret_santa`, 문장 속 token·secret)과 비밀 모양 가림, 멱등, 최소 길이 8, `pwd` 규칙, ID 모양 보존, JSON 문자열 키 규칙, 정상 객체 키
  - 기존 `test_agent_core.test_rows_are_redacted`, `test_agent_log_durability` 등은 고치지 않고 통과
- 손으로 확인한 것: `build_redactor`로 `db_password=`·`--password 값`·`-pSECRET`이 가려지지 않고 `DB_TOKEN=`은 가려지는 것을 확인했다(한계 문서의 근거).
