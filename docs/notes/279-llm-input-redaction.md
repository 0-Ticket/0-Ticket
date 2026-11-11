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
- **근거 ID는 ID 모양으로 건너뛴다.** 필터는 문자열만 봐서 `id_fields`를 모른다. 접두사(`soc.ids.PREFIXES`) + UUIDv7 모양을 건너뛴다. 처음에는 모든 규칙에서 제외했다가 #292 리뷰 뒤 환경변수 값 치환에서만 제외하도록 좁혔다(아래).
- **가림 함수 전달.** `_writer(sink, config, redact=None)`에 선택 인자를 더했다. `_before_start`는 인자 없이 불러 예전처럼 직접 만든다. `_execute`는 `redact` 인자를 받는다.
- **입력 항목은 dict만 온다(openai-agents 0.24.0).** 실제 SDK 실행에서 필터가 받은 항목 16개가 모두 dict였고, `RunItem.to_input_item`이 항목을 `model_dump`/dict 복사로 바꿔 `ResponseInputItemParam`(TypedDict)으로 넘긴다(`agents/items.py`). 객체가 오는 경로는 없다. `_as_json`(dict가 아니면 `jsonable`로 바꿈)은 SDK가 바뀌어 객체가 와도 가림을 건너뛰어 원문이 나가지 않게 하는 방어다. 그 경로는 실제로 만들 수 없어 `_as_json` 자체만 테스트로 고정했다(`test_sdk_input_items_are_dicts_and_objects_are_converted_not_leaked`). SDK를 올릴 때 이 테스트의 첫 단언(모두 dict)이 깨지면 가림 경로를 다시 본다.
- **페이지 이동 표지는 가리지 않는다.** `next_token`·`page_token`·`next_page_token`·`continuation_token`은 비밀이 아닌데 "이름이 `token`으로 끝나는 낱말" 규칙에 걸려 값이 가려졌다(마무리 때 샘플로 확인해 찾음). 이 이름들만 건너뛴다(`_CURSOR_NAME`). `csrf_token=` 같은 다른 `*_token`은 계속 가린다. `tokens_in`·`token_count`·`max_tokens`·`secret_santa`처럼 `token`·`secret`으로 끝나지 않는 이름과 문장 속 낱말("Invalid token provided")은 원래 걸리지 않는다(샘플로 고정).

## PR #292 리뷰 반영 (같은 브랜치에 새 커밋으로 얹음)

리뷰어의 프로브를 고치기 전에 같은 방식으로 직접 돌려 재현했고, 고친 뒤 다시 돌렸다. 재현 테스트를 먼저 써서 실패하는 것을 확인했다(`test_agent_redact.py` 14건, `test_agent_input_redaction.py` 4건 실패).

| 프로브 | 고치기 전 | 고친 뒤 |
|---|---|---|
| `"a-"*n` 가림 시간 8k / 32k / 64k자 | 0.78초 / 12.60초 / 48.89초 | 0.01초 / 0.02초 / 0.05초 |
| 환경변수 값 `pa"ss\word<9>x한글`을 도구 결과(JSON 문자열)에서 | 모델 텍스트에 그대로 남음, 로그(dict)에서는 가려짐 | 둘 다 가려짐 |
| `"authorization": {...}`, `"token": 12345678`, `"secret": [...]` | 객체 값은 그대로, 배열 값은 `[REDACTED]"a", "b"]`로 JSON이 깨짐 | 세 개 모두 `[REDACTED]`, JSON 유지 |
| `pwd=/Secret99` / `PWD=/home/alice` / `pwd=/a/b` | 셋 다 가리지 않음 | `/Secret99`만 가림(나머지 둘은 건너뜀, `/a/b`는 한계) |
| 12턴 × 최대 64k자 가림 비용 | 측정 안 함 | 실제와 비슷한 입력(마지막 호출 약 47.5k자) 12호출 합 0.15초, 최악(`"a-"` 64k자 한 항목 × 12) 0.49초 |

- **정규식.** `_NAMED_SECRET`의 접두 낱말을 낱말당 32자 이하, 최대 4개로 제한했다. 같은 이유로 `_URL_PASSWORD`의 스킴 길이도 31자 이하로 제한했다(이 규칙도 `-`로 이어진 긴 글에서 같은 모양이라 함께 제한했다. 이 규칙만 따로 시간을 재지는 않았다). 시간 상한 테스트는 32,000자에 5초로 넉넉하게 잡았다(고친 뒤 0.02초, 고치기 전 12.6초).
- **가림 전 원문 글자 수 사전 검사는 넣지 않았다.** 넣으면 `budget_exceeded` 줄의 `chars`가 "보낼(가린) 입력의 글자 수"에서 "원문 글자 수"로 바뀌고, 가림 뒤 줄어드는 입력(긴 개인 키 등)의 통과·거부 판정도 달라진다(#278의 `sent=false` 줄 의미 변경). 정규식이 선형이 되어 이 입력의 비용은 위 표처럼 작다. 사람이 정한 조건("의미가 바뀌면 넣지 않는다")에 따랐다.
- **환경변수 값의 JSON 이스케이프 모양.** `registry._dump`와 `runner.wrap_data`는 `json.dumps(..., ensure_ascii=False)` 뒤에 `<`·`>`를 `<`·`>`로 바꾼다. 같은 방식의 모양 둘(이스케이프만, `<`·`>`까지)을 가릴 값에 더했다. 한글은 `ensure_ascii=False`라 그대로다.
- **도구 결과·입력 데이터는 JSON으로 풀어서 가린다.** `<태그>\nJSON\n</태그>` 모양이면 `json.loads`로 풀어 dict 규칙을 적용하고, 바뀐 것이 있을 때만 같은 직렬화로 다시 만든다. 바뀐 것이 없으면 원문 문자열을 그대로 둔다(`test_model_text_is_unchanged_when_nothing_is_masked`). 풀리지 않으면 문자열 규칙만 쓴다. 풀어서 가린 뒤에도 문자열 규칙을 한 번 더 돌려 키 이름에 든 비밀 같은 나머지를 가린다. 이 일은 필터가 아니라 `redact_text` 안에서 한다. 필터와 Agent Log 쓰기가 같은 함수를 쓰므로 둘의 결과가 같다.
- **`pwd` 규칙.** `/`로 시작하고 `/` 구분 경로가 두 단계 이상이면 건너뛴다. `/a/b` 모양 비밀번호는 못 가린다(문서에 적음).
- **ID 모양 면제는 환경변수 값 치환에서만 한다.** 키-값 규칙은 ID에도 적용한다. ID가 `token=`·`password=` 같은 모양으로 나오는 경로가 레포에 있는지 확인했다: `contracts/`에 이름이 token·secret·password·authorization·api_key인 필드가 없고, `src`·`tests`·`config`·`prompts`에서 그런 이름 바로 뒤에 ID가 오는 문자열도 없다. 근거 ID를 깨는 경로는 없어서 멈추지 않았다.
- **알 수 없는 타입은 `TypeError`.** `redact`는 dict·list·str·숫자·불리언·None 외를 만나면 예외를 낸다. 필터에서는 `provider_error`로 끝나고(모델 호출 없음) Agent Log 쓰기에서는 쓰기 실패로 센다. 전체 테스트가 통과해 기존 줄(`jsonable`을 거친 값)은 모두 JSON 값이다. 가림 준비(`build_redactor`) 실패는 "Agent Log 설정이 잘못됐다"와 다른 "비밀 값 가림을 준비하지 못했다"로 알린다.
- **입력 항목의 구조 필드는 가리지 않는다.** "call_id가 비밀 모양 문자열과 겹치는 경우" 테스트를 쓰려면 그 동작이 필요했다. 최상위 `type`·`role`·`call_id`·`id`·`name`·`status`는 그대로 두고 본문만 가린다. 환경변수 값이 SDK의 `call_1_0`과 같아도 도구 호출과 결과의 `call_id`가 `[REDACTED]`로 바뀌어 짝이 깨지는 일이 없다. 본문에 같은 문자열이 있으면 가려진다(테스트로 확인). 사람이 요청한 테스트를 구현한 것이지만 목록에는 없던 동작이라 계획 "바뀐 점"에 적었다.
- **테스트.** `test_tool_name_and_call_ids_are_not_touched`(가림을 꺼도 통과하던 테스트)는 위 동작을 확인하는 `test_call_ids_and_tool_names_survive_even_when_they_look_like_the_env_secret`으로 바꿨다. 도구 결과가 든 두 번째 호출에서 가림이 실패하는 경우, 이스케이프 문자가 든 환경변수 값, 객체·비문자열 값 아래의 비밀 키, 가림 준비 실패 메시지, 크기별 시간 상한, `pwd=/Secret99`, 객체 값 샘플을 더했다.
- **마무리 점검(2026-11-11, 코드는 바뀌지 않았다).**
  - 정규식 아홉 개(`_URL_PASSWORD`, `_JSON_SECRET_KEY`, `_KEY_VALUE`, `_NAMED_SECRET`, `_PWD`, `_BEARER`, `_AUTH_SCHEME`, `_ID`, `_ENVELOPE`)를 각각 `a-`·`a.`·`a_`·`a:`·`a://`·`://`·`a:b@`·따옴표·공백·`password `·`Bearer `·`token=` 등 반복 입력 31가지 × 8k·32k·64k자로 쟀다. 패턴별 최악은 `_URL_PASSWORD` 0.015초, `_NAMED_SECRET` 0.012초이고 0.5초를 넘는 것은 없었다. 전체 가림 함수(평문과 봉투)의 최악은 0.075초였다. 고칠 정규식이 없어, 모든 규칙이 한 번에 지나가는 시간 상한 테스트만 더했다(`test_every_rule_stays_fast_on_repeated_input`, 32,000자에 5초).
  - `_ENVELOPE`은 손으로 쓴 문자열이 아니라 실제 `registry._wrap(_dump(...))`와 `runner.wrap_data(...)` 출력으로 확인한다(`test_envelope_is_the_real_registry_and_wrap_data_output`). 태그 이름에 `_`를 못 받게 바꾸면 실패하는 것을 확인했다.
  - 구조 필드 면제는 입력 항목의 최상위 키에만 적용된다. 중첩 값과 `content`·`arguments`·`output` 안의 같은 이름 키는 계속 가려진다(`test_structural_key_exemption_applies_only_to_top_level_keys`). 면제 키를 `content`·`arguments`·`output`까지 넓히거나 면제를 없애면 실패하는 것을 확인했다.
  - PR 커밋 8개의 메시지에 `Co-Authored-By`·`Claude-Session`·"Generated with" 같은 AI 표시가 없다.
- 항목별 가림 캐시는 만들지 않았다(사람이 정함). 정규식이 선형이 된 뒤 12턴 비용은 위 표와 같다.

## 다음 사람이 알아야 할 것

- **8자 미만 환경변수 비밀은 가려지지 않는다.** 개발용 `admin` 같은 키가 그렇다. 설정에 짧은 키를 쓰면 외부 LLM으로 나간다.
- **`db_password=`·`MYSQL_PASSWORD=`처럼 낱말 앞에 다른 글자가 붙은 `password`·`api_key`는 여전히 못 가린다**(`\bpassword`가 `_`와 `p` 사이에서 맞지 않음). `DB_TOKEN=`은 새 규칙으로 가려진다. `password`·`api_key`에도 같은 접두 규칙을 쓰면 되지만 이번 범위가 아니라 두었다(`security.md` 한계에 적음).
- **카멜 케이스 이름(`accessToken=`, `clientSecret=`)은 못 가린다.** 낱말 경계를 `_`·`-`로만 본다.
- **명령줄 모양(`--password 값`, `-pSECRET`)과 이름·값 쌍 헤더는 못 가린다.** SSH `processes` 점검의 위험(#213)은 그대로다.
- **`ps`·`auth_log` 같은 결과는 자른 뒤에 가린다.** 잘린 조각난 환경변수 값은 못 가린다(#213 기록과 같다).
- **가림은 판정 증거도 가린다.** 모델은 `[REDACTED]`를 본다. 실제 모델로 판정 품질이 달라지는지는 확인하지 않았다.
- **`runner.py`의 `_execute`·`_writer`는 #280과 겹친다.** 머지 순서는 담당자가 팀과 정한다.
- **D-036의 읽는 규칙은 같다.** 바뀐 것은 model 줄 `input`과 `records` 도구 줄 `output`이 가림 적용 후 값이라는 점뿐이다. 모델 출력 줄·`details`·도구 인자 줄은 쓰기 직전에만 가린다.
- **가림 실패(`provider_error`)는 L1이 최초 포함 3회까지 다시 시도하지만 같은 입력이면 결과도 같다**(D-025). 가림 실패는 결정적이라 재시도해도 소용이 없고 마지막에 `held`가 된다. 실패 종류를 따로 센 L1 재시도 제외는 이번 범위 밖이다.
- **`<태그>` JSON이 아닌 문자열(모델 메시지, 도구 호출 인자)의 객체·배열 값 아래 비밀 키는 못 가린다**(`security.md` 한계). `registry._dump`·`runner.wrap_data`의 직렬화나 태그 모양이 바뀌면 `redact.py`의 `_ENVELOPE`·`_envelope`도 같이 고쳐야 한다.
- 가림에 쓸 환경변수 값은 `run_task`마다 `build_redactor`가 다시 읽는다. 실행 중에 바뀐 값은 다음 run부터 반영된다.
- **이 변경과 무관한 기존 현상 두 가지.** 둘 다 `origin/main`(`d0247ac`)을 그대로 체크아웃해 `tests/test_migrate.py`와 `tests/test_tools_ssh.py`를 돌렸을 때 똑같이 나왔다(144건 통과, 1건 실패).
  - `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`: Windows가 줄바꿈이 든 파일명을 만들지 못해 `OSError`로 실패한다(#278 기록에도 있다). Linux CI에서는 돈다.
  - `tests/fake_ssh.py:107`의 `FakeSshServer._start.<locals>.silent()` 태스크가 "Task was destroyed but it is pending!" 경고를 낸다. 테스트는 통과하고 `ssh` 마커 테스트 파일(`test_tools_ssh.py`)에서 나온다. 가림과 관계없다.

## 확인 방법

- `PYTHONUTF8=1 uv run ruff format --check .`: 통과
- `PYTHONUTF8=1 uv run ruff check .`: 통과
- `PYTHONUTF8=1 uv run python scripts/generate_contracts.py --check`: 통과(계약은 바뀌지 않았다)
- `PYTHONUTF8=1 uv run pytest`: 1,459건 통과, 1건 실패(위 `test_migrate`, 변경과 무관). #292 리뷰 반영 뒤의 코드로 다시 돌린 값이다(그 전에는 1,435건 통과). 기준은 `origin/main`(`d0247ac`)이다.
- 마무리 점검에서 테스트 22건을 더했다(코드는 그대로). 전체 `pytest`는 다시 돌리지 않았고, 두 파일(`test_agent_redact.py`, `test_agent_input_redaction.py`)만 83건 통과를 확인했다. 전체는 위 1,459건에 22건을 더한 1,481건 통과, 1건 실패로 예상하지만 돌려서 확인한 값은 아니다. db·qdrant·embedder·elk·ssh·llm 마커 테스트는 기본 실행에서 빠진다
- 테스트를 먼저 썼다. 구현 전에는 새 테스트 중 규칙·필터를 보는 것이 실패했다(샘플 마스킹, 최소 길이, `pwd`, ID 보존, 필터).
- 주요 테스트
  - `tests/test_agent_input_redaction.py`: 가짜 모델 입력과 Agent Log에 비밀이 없음(도구 결과 세 종류, `task.data`), 로그 model 줄을 이어 붙인 입력이 모델이 받은 입력과 같음, 여러 턴과 형식 오류 재요청에서 앞 입력이 뒤 입력의 접두이고 `input_reset`이 없음, 가림 실패 시 모델 호출 없음·`provider_error`·`sent=false` 줄, 환경변수 값이 ID 조각과 겹쳐도 ID·근거 인용 유지, 짧은 환경변수 값은 그대로, 도구 이름과 `call_id`는 그대로
  - `test_without_the_filter_the_model_would_receive_the_secrets`: 대조 시험이다. 가림 함수가 아무것도 안 가리면 같은 시나리오에서 비밀이 모델 입력에 그대로 있다. 위 테스트들이 `run_task` → `Runner.run_sync` → SDK 입력 필터 → 가짜 모델 경로를 실제로 거친다는 증거다(필터 함수를 직접 부르는 테스트는 없다)
  - `test_normal_fields_reach_the_model_unchanged`: `next_token`, `tokens_in`, `PWD=/home/alice`가 SDK 경로로 모델에 그대로 간다
  - `tests/test_agent_redact.py`: 샘플(`tests/fixtures/agent/redact_samples.json`)의 정상 문자열 불변(`next_token` 등 페이지 이동 표지, `tokens_in`·`token_count`·`max_tokens`·`secret_santa`, 문장 속 token·secret)과 비밀 모양 가림, 멱등, 최소 길이 8, `pwd` 규칙, ID 모양 보존, JSON 문자열 키 규칙, 정상 객체 키
  - 기존 `test_agent_core.test_rows_are_redacted`, `test_agent_log_durability` 등은 고치지 않고 통과
- 손으로 확인한 것: `build_redactor`로 `db_password=`·`--password 값`·`-pSECRET`이 가려지지 않고 `DB_TOKEN=`은 가려지는 것을 확인했다(한계 문서의 근거).
