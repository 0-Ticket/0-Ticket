---
issue: 209
date: 2026-11-04
owner: Interludeal
supersedes: []
---

# 에이전트 코어 만들기: 결정 반영, run_agent, Agent Log 저장

## 목표

L1·L2·L3 파이프가 부르는 단 하나의 접점 `run_agent(AgentTask) -> AgentResult`(동기)를 만든다. 모든 모델·도구 호출을 Agent Log로 `agent_logs`에 남긴다.
가짜 모델 시나리오로 정상 판정과 실패 6종+`log_error`가 예외 없이 `AgentResult`로 나오면 끝이다. 실제 LLM 연결은 #210에서 붙인다.

## 방법

결정 반영

- 에이전트 프레임워크(D-022)와 에이전트 구조(D-024)를 확정으로 옮긴다(이 계획의 확정 커밋에서 함).
- `docs/security.md` "밖에서 온 문자열" 절의 기존 문장은 그대로 두고, 다음 문장을 덧붙인다: "도구는 단계별 허용 목록으로, 인자는 도구별 형식 검사로, 횟수는 작업별 예산으로 막고, 판정은 출력 형식과 근거 ID 검사를 통과해야 쓴다."
- 의존성 `openai-agents==0.24.0`, `openai==3.42.1`을 고정한다. 함께 들어오는 패키지는 `uv.lock`에 맡긴다.

`run_agent`

- 공개 함수는 `run_agent(task)` 하나이고 동기다. 안에서 `Runner.run_sync`를 쓴다. 모델과 Agent Log 기록기(`log_sink`)를 받는 내부 함수를 따로 두고, `run_agent`는 설정에서 만든 기본 모델과 DB 기록기로 그 함수를 부른다. 기본 모델은 #210에서 붙이고, 이 이슈에서는 테스트가 가짜 모델과 메모리 기록기를 넣는다.
- `AgentTask` 필드: `stage`(`l1`/`l2`/`l3`), `task`, `prompt`(`TaskPrompt(text, version)`), `data`, `output_contract`(계약 이름 `str`), `cited_ids`(출력에서 근거 ID를 꺼내는 함수), `subject_type`·`subject_id`, `allowed_evidence_ids`, `domains`, `attempt`. 허용 도구 목록은 넣지 않는다(`stage`로만 정한다).
- `AgentResult`: `ok`, `output`(계약을 통과한 값, 실패하면 `None`), `failure`, `detail`(안전한 상세만), `run_id`(`new_id("run")`), `usage`(턴·도구 호출·도구 오류·토큰·시간), `cited_evidence_ids`(중복 없음).
- failure: `format_error`, `evidence_id_error`, `budget_exceeded`, `rate_limited`, `provider_error`, `cancelled`, `log_error`. 도구 오류는 failure가 아니고 횟수만 `usage`에 센다.
- 처리 순서
  1. 작업 검사
  2. 프롬프트 합성. 이 이슈에서는 `base.md` 자리와 작업 프롬프트만 넣는다. 5층 합성은 #210에서 한다. 합친 내용의 해시를 `prompt_version`으로 쓴다.
  3. `Runner.run_sync`. `output_type`은 쓰지 않고 `parallel_tool_calls=False`로 둔다. 진입점에서 `set_tracing_disabled(True)`를 부른다.
  4. JSON 파싱
  5. 출력 계약 최상위에 `decided_at`이 있으면 현재 시각(UTC epoch ms)으로 덮어쓴다. 모델이 낸 값은 쓰지 않는다.
  6. `validate_contract(output_contract, data)`(#193)
  7. 실패하면 대화를 이어 "형식 오류: <위반 경로와 규칙>"만 보내 1회 재요청한다. 입력 값은 넣지 않는다. 이 재요청도 `max_turns` 안에서 센다. 또 실패하면 `format_error`
  8. 근거 장부 검사. 장부는 `allowed_evidence_ids`로 시작하고, 장부에 없는 근거 ID는 `evidence_id_error`
  9. Agent Log 줄을 모두 쓴다. 실패하면 `log_error`
  10. 항상 `AgentResult`를 반환한다(예외를 밖으로 내지 않음)
- `data`는 구분자로 감싸 user 메시지로만 전달한다.

Agent Log

- 모델 호출 한 번, 도구 호출 한 번이 각각 한 줄이다. 필드는 Agent Log 계약(#193)을 따른다. `id`는 `new_id("agl")`, `seq`는 1부터, `tokens_in`·`tokens_out`은 도구 줄에서 null이다. 정수 칸은 Python int로 넣는다.
- `details`: `task`, `prompt_version`(`model` 줄), `attempt`, `failure`(`outcome = error`인 줄), `validation`(그 실행의 마지막 `model` 줄: `ok`/`format_error`/`evidence_id_error`).
- 쓰기 전에 아래 세 가지를 `[REDACTED]`로 바꾸고, 그다음 `validate_contract("agent_log", row)`를 거친다.
  1. 설정의 `*_env`가 가리키는 환경변수의 실제 값
  2. DB 주소의 비밀번호
  3. `password=`, `Authorization: Bearer`, `api_key` 모양의 값
- 출력이 없으면 `output`은 SQL NULL로 넣는다(JSON null 아님, #193 기록).
- DB 기록기는 `DATABASE_URL`로 접속하고 `agent_logs`에만 쓴다. `run_agent`가 반환하기 전에 모든 줄을 커밋한다. 쓰기가 실패하면 `ok=True`를 주지 않고 `log_error`로 끝낸다. 이때 `detail`에 DB 주소와 비밀 값을 넣지 않는다.

설정

- `config/default.toml`은 커밋한다. `config/local.toml`은 커밋하지 않는다(`.gitignore`의 `config/local.*`가 이미 막고 있다). 기본 위에 local을 덮어쓴다(설정 파일 TOML, D-002).
- 이 이슈의 로더는 `[llm]`·`[agent]`·`[tools]`만 읽는다. 비밀 값은 넣지 않고 환경변수 이름만 적는다. 공통 로더가 생기면 바꾼다.

가짜 모델

- `tests/fixtures/agent/*.json` 시나리오대로 도구 호출과 최종 JSON을 낸다. `tests/` 안에서만 쓴다.
- 시나리오 파일 형식은 `docs/notes/`에 적는다.

## 바꿀 곳

- `docs/decisions.md`: 에이전트 프레임워크(D-022), 에이전트 구조(D-024)를 확정으로. 이 계획의 확정 커밋에서 함
- `docs/security.md`: "밖에서 온 문자열" 절에 장치 문장 한 줄 덧붙임
- `pyproject.toml`, `uv.lock`: `openai-agents==0.24.0`, `openai==3.42.1`
- `config/default.toml`: `[llm]`·`[agent]`·`[tools]` 기본값(비밀 값 없음)
- `src/soc/agent/`: `run_agent`, 데이터 클래스, 근거 장부, 출력 검증, 비밀 값 가림, Agent Log 기록기(메모리·DB), 설정 로더
- `src/soc/agent/prompts/base.md`: 1층 자리(내용은 #210)
- `tests/`: 가짜 모델, `tests/fixtures/agent/*.json` 시나리오, 단위 테스트, `db` 마커 테스트

## 다른 코드와 맞물리는 곳

- **새로 만드는 공개 인터페이스(파이프가 부름).** `run_agent(AgentTask) -> AgentResult`(동기), `AgentTask`, `TaskPrompt`, `AgentResult`, failure 값 7종(`log_error` 포함).
- **기존 것을 그대로 씀.** `soc.contracts.validate_contract`, `soc.ids.new_id`, 테이블 `agent_logs`(#193). 바꾸지 않는다.
- **새 설정 파일.** `config/default.toml`의 `[llm]`·`[agent]`·`[tools]`.
- **연구 레포 설계와 다른 점.** `log_error`와 동기 `run_agent`는 연구 레포 설계 문서와 파이프 전달 사항에 아직 없다. 파이프 담당에게 알린다.

## 범위 밖

- 기본 LLM(D-009, Foundry) 결정과 실제 모델 연결, 예산, 429 처리, 5층 프롬프트 내용 → #210
- 도구 구현 방식(D-023) 결정, 도구 레지스트리, `AGENT_DATABASE_URL`과 `.env.example` → #211
- asyncssh 결정과 SSH 도구(D-011) `shlex.quote` 메모 → #213
- 실행기(`AgentWorker`) → #215

## 완료 기준

- [ ] 에이전트 프레임워크(D-022)·에이전트 구조(D-024)가 `docs/decisions.md`에 확정으로 있다
- [ ] `docs/security.md` "밖에서 온 문자열" 절에 기존 문장이 그대로 있고, 장치 문장이 덧붙어 있다
- [ ] 담당자 확인 작업(크레딧 구독의 "Sold by Azure" 표시, 배포 가능 리전, TPM)을 했고 결과를 `docs/notes/`에 적었다. TPM이 30K 미만이면 할당량 증가를 요청했고 승인 전까지 Groq로 개발한다는 사실도 적었다
- [ ] 가짜 모델의 정상 Verdict 시나리오가 `ok=True`와 계약을 통과한 `output`을 낸다
- [ ] 형식 오류 2회(재요청 뒤에도 실패) → `format_error`. 재요청 메시지에 입력 값이 없다
- [ ] 장부에 없는 근거 ID 인용 → `evidence_id_error`
- [ ] `max_turns` 초과(`MaxTurnsExceeded`) → `budget_exceeded`
- [ ] 모델이 낸 `decided_at`이 현재 시각으로 덮어써진다
- [ ] 어떤 실패에도 예외가 밖으로 나오지 않는다
- [ ] 환경변수 없이도 트레이싱이 꺼져 있음을 테스트로 확인한다
- [ ] 가짜 모델 시나리오 파일 형식을 `docs/notes/`에 적었다
- [ ] 가짜 모델 실행 뒤 `agent_logs`에 줄 수·`seq`·`kind`가 맞게 들어간다
- [ ] 도구 줄의 `tokens_in`·`tokens_out`이 null이다
- [ ] 실패한 실행도 `outcome=error`와 `details.failure`가 남는다
- [ ] 비밀 값 가림 테스트가 있다(`tests/fixtures/`의 가짜 값으로 세 가지 모두)
- [ ] `run_agent` 반환 시점에 모든 줄이 커밋돼 있다
- [ ] Agent Log 쓰기가 실패하면 `ok=False`, `failure=log_error`이고 `detail`에 DB 주소·비밀 값이 없다
- [ ] `config/default.toml`이 커밋돼 있고, `config/local.toml`이 덮어쓴다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

이슈 본문과 달라진 점

- **결정 범위.** 이 이슈에서는 에이전트 프레임워크(D-022)와 에이전트 구조(D-024)만 확정한다. 팀 합의를 받았다(L1·L2·L3 담당, #209 계획 단계). 나머지는 그 결정을 처음 쓰는 이슈로 옮겼다. 쓰지 않는 결정을 미리 확정하지 않기 위해서다.
  - 기본 LLM(D-009, Foundry) → #210
  - 도구 구현 방식(D-023, 함수 도구 레지스트리) → #211
  - asyncssh 새 결정(라이선스 EPL-2.0 OR GPL-2.0-or-later, 수정 없이 import한다는 메모 포함) → #213
  - SSH 도구(D-011) `shlex.quote` 메모 → #213
- **`docs/decisions.md` 기록 줄은 날짜 대신 이슈 번호를 기준으로 적는다(`#209 · …, 팀 합의(#209)`).**
- **security.md는 교체하지 않고 덧붙인다.** 기존 문장 "로그 내용이 어떤 도구를 부를지, 어떤 판정을 내릴지를 직접 바꾸지 못하게 한다"를 남긴다. 형식과 근거가 맞아도 로그 속 지시에 판정이 끌려갈 수 있으므로, 판정 조작 금지 문장을 지우지 않는다.
- **failure에 `log_error`를 추가한다.** 근거로 인용된 `agl_` 기록이 DB에 없는데 `ok=True`를 줄 수는 없고, 기존 6종 중 맞는 값이 없어서다. L1 처리는 `provider_error`와 같다: 다시 하고, 재시도 한도를 넘으면 `held`.
- **`AGENT_DATABASE_URL`은 #211로 옮긴다.** 이 이슈에는 이 변수를 쓰는 코드가 없다(필요한 만큼만 만든다).

질문과 답

1. 결정 범위: D-022·D-024만 확정한다(위).
2. security.md: B, 덧붙이기(위).
3. 동기·비동기: A, 동기 `run_agent(task)`이고 안에서 `Runner.run_sync`를 쓴다. 파이프의 `handle`과 psycopg가 동기이기 때문이다. #215의 "스레드마다 이벤트 루프"는 "스레드마다 실행 루프"로 읽는다.
4. Agent Log 쓰기 실패: A, `log_error`(위).
5. `AGENT_DATABASE_URL`: B, #211(위).
6. 의존성: A, `openai-agents==0.24.0`과 `openai==3.42.1`을 함께 고정한다. 설계가 검증한 조합이다. 함께 들어오는 패키지는 `uv.lock`에 맡긴다.
7. 설정 파일: A, `config/default.toml`(커밋)과 `config/local.toml`(커밋 안 함). 이 이슈는 `[llm]`·`[agent]`·`[tools]`만 읽는다.

빈칸에 대한 답

- 주입: 공개 함수는 `run_agent(task)` 하나다. 내부 함수가 `model`과 `log_sink`를 받는다. 테스트는 가짜 모델과 메모리 기록기를 쓴다. 운영 모델은 #210에서 붙인다.
- 비밀 값 가림: 세 가지(`*_env`가 가리키는 환경변수의 실제 값, DB 주소의 비밀번호, `password=`·`Authorization: Bearer`·`api_key` 모양의 값)를 `[REDACTED]`로 바꾼다.
- 형식 오류 재요청: 대화를 이어 "형식 오류: <위반 경로와 규칙>"만 보낸다. 입력 값은 넣지 않고, `max_turns` 안에서 센다.
- `decided_at`: 모델 값을 쓰지 않는다. 출력 계약 최상위에 있으면 검증 전에 현재 시각(UTC epoch ms)으로 덮어쓴다. 5층 자동 프롬프트에 "decided_at은 비워 두라"를 넣는다. 5층은 #210에서 만든다.

## 바뀐 점
