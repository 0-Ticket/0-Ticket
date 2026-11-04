---
issue: 210
date: 2026-11-04
owner: Interludeal
plan: 210-llm-prompts.md
supersedes: []
---

# LLM 연결·429 재시도·입력 예산과 프롬프트 5층을 붙였다

## 한 일

- `run_agent`가 설정의 `[llm]` 값으로 OpenAI 호환 제공자 하나에 연결한다. 연결은 `OpenAIChatCompletionsModel` + `AsyncOpenAI(base_url, api_key, timeout, max_retries=0)` 하나이고, 제공자는 `config/local.toml`의 `base_url`·`model`·`api_key_env`만 바꿔 고른다(기본 LLM, D-009: Azure Foundry `gpt-oss-120b`, 되돌릴 곳 Groq·Ollama). `config/default.toml`은 비워 두어 그대로면 `provider_error`다.
- 429는 모델 호출을 감싼 `RetryingModel`이 `Retry-After`(초) 또는 1·2·4초를 기다려(한 번에 최대 60초) `rate_limit_retries`번까지 다시 부른다. 넘으면 `rate_limited`, 재시도 횟수는 그 model 줄의 `details.retries`에 남는다. 타임아웃·인증 오류는 재시도 없이 `provider_error`다.
- 모델 호출마다 `call_model_input_filter`가 system 지시 + 입력 항목(JSON) 글자 수를 단계별 `max_input_chars`(32,000 / 64,000 / 48,000)와 비교해, 넘으면 보내지 않고 `budget_exceeded`로 끝낸다. 보내지 않은 호출도 model 줄 하나로 남는다.
- 지시문은 5층(공통 `base.md` → 단계 `l1/l2/l3.md` → 도메인 `domains/web·cloud.md` → 파이프의 `TaskPrompt` → 자동)으로 합성하고, 합친 내용의 SHA-256이 `prompt_version`이다. 자동 층은 "최대 N턴 안에 답한다", 출력 계약 요약(최상위 필드·필수·타입·enum), decided_at 안내다.
- 금지 문구(`FORBIDDEN_PHRASES`)가 든 `TaskPrompt`는 만들 때 `ValueError`다. 2·3층 파일은 테스트가 같은 목록으로 검사한다.
- 단계별 `reasoning_effort`(L1 low, L2·L3 medium)를 Chat Completions의 `reasoning_effort`로 보낸다.

## 계획과 달라진 점

- **모듈 이름.** 합성은 `soc.agent.compose`, 연결·재시도·글자 수는 `soc.agent.llm`에 두었다. `src/soc/agent/prompts/`가 이미 프롬프트 파일 폴더라 `prompts.py`를 만들면 이름이 겹친다. `runner.compose_instructions`는 `compose.compose_instructions(task, *, max_turns)`로 옮겼다. `runner._has_top_level`도 `compose.has_top_level_field`로 옮겼다.
- **금지 문구 목록에 두 개를 더했다.** "ignore all previous", "시스템 프롬프트". 계획의 예시 다섯 개는 그대로 있다. "ignore previous"는 "ignore all previous"를 잡지 못하고, "system prompt"의 한국어 표현도 같은 뜻이라서다.
- **`run_task`에 `sleep` 인자를 더했다**(기본 `asyncio.sleep`). 테스트가 기다리지 않게 바꿔 끼우는 자리다. `soc.agent.llm.build_model`에는 `http_client` 인자를 두었다. 테스트가 가짜 전송 계층(`httpx2.MockTransport`)을 넣어 실제 openai 클라이언트가 만든 요청(주소·키 헤더·model·reasoning_effort)과 실제 429 응답 처리를 네트워크 없이 확인하는 자리다.
- **설정 키는 필수다.** `[agent.<단계>]`의 `max_input_chars`·`reasoning_effort`, `[llm]`의 `rate_limit_retries`·`timeout_seconds`가 없으면 `provider_error`("예상하지 못한 오류(KeyError)")로 끝난다. 빠진 설정을 예산 없음으로 넘기지 않기 위해 기본값을 코드에 두지 않았다.
- **#209 테스트에서 고친 곳**(지우거나 건너뛴 것은 없다)
  - `tests/test_agent_core.py`의 `CONFIG`에 새 설정 키를 기본값으로 넣었다. 새 키가 필수라서다.
  - 같은 파일의 `run()` 도우미가 `sleep=no_sleep`을 넘긴다. 429 재시도가 실제로 기다리지 않게 하기 위해서다.
  - `test_retry_counts_toward_max_turns`는 l1 설정을 `{"max_turns": 1}`로 통째로 바꾸던 것을 `max_turns`만 바꾸게 고쳤다. 새 필수 키가 빠져 `provider_error`가 나서다.
  - `tests/fixtures/agent/rate_limited.json`을 429 한 번에서 네 번(처음 1회 + 재시도 3회)으로 바꿨다. 이제 429 한 번은 재시도로 넘어가므로, "rate_limited로 끝난다"를 보려면 설정 횟수만큼 계속 429여야 한다.

## 다음 사람이 알아야 할 것

- **Azure 계정 확정 후 할 일(#215).** 이 이슈에서는 실제 제공자에 한 번도 연결하지 않았다.
  - 담당자 확인 작업: 크레딧 구독의 "Sold by Azure" 표시, `gpt-oss-120b` 배포 리전, TPM. TPM이 30K 이상이면 Foundry를 쓰고, 미만이면 할당량 증가를 요청하고 그동안 Groq를 쓴다.
  - `config/local.toml`(커밋 안 함): `[llm]`에 `base_url = "https://<리소스 이름>.openai.azure.com/openai/v1/"`, `model = "<배포 이름>"`, `api_key_env = "LLM_API_KEY"`. 키 값은 `.env`의 `LLM_API_KEY`에만 둔다.
  - 실제 호출 테스트: `llm` 마커 테스트를 #215에서 만들고 `uv run pytest -m llm`으로 돌린다.
  - `strict` 수용 여부: #211 레지스트리로 도구 정의에 strict를 켠 채 도구 호출 → JSON 답 1건을 확인한다. 거부되면 `strict_mode = false`.
  - Ollama의 `reasoning_effort` 처리는 확인하지 않았다. 받지 않는 제공자가 있으면 #215에서 확인한다.
- **SDK가 입력 필터를 `on_llm_start`보다 먼저 부른다**(openai-agents 0.24.0). 그래서 예산 초과 줄은 훅이 아니라 필터가 `LogRecorder.add_budget_exceeded`로 직접 만든다. 이 줄은 `input = {"chars", "max_input_chars"}`, `output`·토큰 null, `outcome = error`, `details.failure = budget_exceeded`이고 `details.retries`는 없다. 앞의 성공한 model 줄은 `ok` 그대로다. SDK를 올리면 이 순서를 다시 확인한다.
- **필터에서 올린 예외는 SDK가 감싸지 않고 그대로 올린다**(0.24.0). 필터가 `_Stop("budget_exceeded")`를 바로 올려 `run_task`가 받는다.
- **재시도는 `RetryingModel` 하나다.** openai는 `max_retries=0`, SDK `ModelSettings.retry`는 None이다. 둘 중 하나를 켜면 재시도가 겹친다. `RetryingModel`은 `RateLimitError`만 다시 부르고 5xx·연결 끊김은 다시 부르지 않는다(파이프가 `provider_error`로 다시 한다).
- **model 줄의 `details.retries`.** 보낸 model 줄에는 항상 있다(재시도가 없으면 0). 실패로 끝난 호출(`rate_limited`)에도 남는다. 한 호출의 재시도는 한 줄 안에서 세고, 그 줄의 `duration_ms`에는 기다린 시간이 들어간다.
- **`prompt_version`이 #209 때와 달라졌다.** 5층이 붙었기 때문이다. 프롬프트 파일, `max_turns`, 출력 계약 schema(#217 Hunt 등)가 바뀌어도 바뀐다. 실행마다 바뀌는 값은 넣지 않아 같은 작업이면 같다.
- **출력 계약 요약은 비공개 `soc.contracts.validate._CONTRACTS`와 `SCHEMA_DIR`을 읽는다.** 계약 모듈(#192)에 계약 schema·최상위 필드를 조회하는 공개 함수가 생기면 `soc.agent.compose`를 바꾼다. `$ref`는 `파일#/포인터` 모양만 따라간다.
- **에이전트 출력에는 `verdict`처럼 하위 객체 계약을 쓴다.** 요약은 최상위 필드를 기계적으로 나열하므로, `ticket`·`hunt` 같은 레코드 전체 계약을 `output_contract`로 넘기면 모델에게 `id`·`created_at`까지 쓰라고 안내하게 된다.
- **금지 문구는 부정문도 잡는다.** 비교는 대소문자를 구분하지 않고 공백을 하나로 줄인 부분 문자열이다. 2층에서 "대응을 실행하지 않는다"라고 쓰면 테스트가 실패한다(그 규칙은 1층에 있다). 1층(`base.md`)과 5층은 검사하지 않는다.
- **`TaskPrompt`를 만들 때 `ValueError`가 나는 조건(파이프 담당).** #209의 조건(빈 text, 빈 version)에 더해, text에 `FORBIDDEN_PHRASES` 중 하나가 들어 있으면 거부한다. 메시지에 입력 값은 넣지 않는다.
- **3층 순서.** `domains`는 들어온 순서와 상관없이 web → cloud 순서로 붙이고 중복은 뺀다. 순서 때문에 해시가 달라지지 않는다.
- **키가 필요 없는 제공자.** `api_key_env = ""`이면 고정 자리표시 키 `"no-key"`를 보낸다(비밀 아님). `api_key_env`가 있는데 환경변수가 비어 있으면 `provider_error`("LLM 키 환경변수(LLM_API_KEY)가 비어 있다")다. 환경변수 이름은 비밀이 아니라 detail에 넣었다.
- **openai 3.x 클라이언트의 다른 환경변수.** `base_url`과 `api_key`는 항상 명시해서 넘기므로 `OPENAI_BASE_URL`·`OPENAI_API_KEY`는 쓰이지 않는다. `OPENAI_ORG_ID`·`OPENAI_PROJECT_ID`는 따로 막지 않았다. 개발 환경에 설정돼 있으면 요청 헤더에 붙을 수 있다.
- **2층 프롬프트는 L1·L2·L3 담당 리뷰 전이다.** 판단 순서가 담당 의도와 다르면 그 담당이 고친다.
- **Windows에서 `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`이 실패한다.** 줄바꿈이 든 파일 이름을 Windows가 만들지 못해서다. `origin/main`에서도 같고 이 이슈와 관계없다. CI(Linux)에서는 통과한다.

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 392건 통과, 1건 실패(위 Windows 전용 실패, `origin/main`에서도 같음). 로컬 Windows에서 실행했다
- 새 테스트(모두 네트워크 없음)
  - `tests/test_agent_llm.py`: 세 제공자 설정의 클라이언트(base_url·model·키·`max_retries=0`·timeout), 빈 연결 설정·키 환경변수 없음, 가짜 전송 계층으로 실제 요청 주소·키 헤더·model·reasoning_effort, 429 재시도(1·2·4초, Retry-After 2.5초·120→60초·읽을 수 없는 값), 설정 횟수 뒤 `rate_limited`와 `details.retries`, 실제 openai 429 응답 재시도, 타임아웃·인증 오류는 재시도 없이 `provider_error`, detail에 키·주소·base_url 없음, 예산(첫 호출 초과·한도와 같으면 보냄·중간 호출 초과와 앞 줄 ok)
  - `tests/test_agent_prompts.py`: 1층이 모든 단계·도메인 조합에 들어감, 층 순서, 2·3층 금지 문구 없음, 금지 문구 `TaskPrompt` 거부(대소문자·공백 변형 포함), 자동 층(턴 문장·계약 요약·decided_at), 해시(같은 입력 같음·한 글자 다름·domains 순서 무관)
  - `tests/test_agent_config.py`: 새 기본값, 제공자 예시는 주석으로만
- 실제 제공자 호출은 하지 않았다(#215).
