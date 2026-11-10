---
issue: 279
date: 2026-11-10
owner: Interludeal
supersedes: []
---

# 외부 LLM으로 가는 비밀 값과 Agent Log 가림 범위 정하기

## 목표

도구 결과와 입력 데이터에 섞인 비밀 값이 외부 LLM 제공자로 나가기 전에 가려지고, Agent Log의 입력 줄과 도구 줄이 모델에게 실제로 보낸 내용과 같아진다. 가림 규칙이 정상 로그 문자열(sudo 줄의 `PWD=`, 흔한 낱말인 사용자 이름)을 바꾸지 않는다. 가림의 범위와 한계가 `docs/security.md`에 적힌다.

## 방법

기준은 `origin/main`(`2ab47c0`, #278 머지 뒤)이다. 이슈의 링크는 #278 이전 커밋 기준이라 줄 번호가 다르다. C1은 현재 main에서도 그대로다: `ToolSession.invoke`는 결과를 가림 없이 돌려주고, 가림은 `RowWriter.prepare`(Agent Log 쓰기 직전)에서만 돈다. C9 재현(`PWD=/home/alice`, 환경변수 값 `admin`)과 `token=`·`Authorization: Basic`·`--password 값` 미탐도 `build_redactor`를 직접 불러 확인했다.

### C1. SDK 입력 필터 한 곳에서 모델 입력을 가린다 (후보 B)

- 지금의 `call_model_input_filter`(`runner._execute`의 `check_budget`)가 입력 항목마다 가림을 적용한 입력을 돌려준다. 대상은 `task.data`(첫 사용자 메시지), 도구 결과, 형식 오류 재요청, 앞 모델 출력이다. system 지시(`instructions`)는 우리가 만든 문장이라 가리지 않는다.
- 순서: 가림 → 입력 예산 검사(`max_input_chars`, 가린 입력의 글자 수) → 돌려줌. SDK는 필터 결과를 `on_llm_start`에 넘기므로 Agent Log의 model 줄 `input`이 모델이 받은 입력과 같아진다. D-036의 "이어 붙이면 그 호출의 전체 입력"이 맞는 말이 된다.
- **같은 입력 이력이면 항상 같은 결과.** 가림은 항목 하나를 입력으로 받는 순수 함수다. 항목끼리 영향이 없고 호출 사이에 상태를 두지 않는다. 그러면 앞 호출 입력의 가림 결과가 다음 호출 입력의 가림 결과의 접두라서 D-036 `input_from` 접두 비교가 흔들리지 않는다. 가림은 멱등이어야 한다(Agent Log 쓰기 직전 가림이 한 번 더 돌아도 같다).
- **Agent Log 쓰기 직전 가림(`RowWriter.prepare`)은 남긴다.** 모델 출력 줄, `details`, 도구 인자 줄은 이 길로만 가려진다. 이 줄들은 모델이 낸 원문과 다를 수 있다. 이 차이는 표시 없이 문서에 적는다(C9, 아래).
- 가림 함수는 `run_task`에서 한 번 만들어 필터와 `RowWriter`가 함께 쓴다. 가림 함수를 만드는 방법(인자 전달 모양)은 개발 때 정한다.
- 도구(`soc.tools`)와 `ToolRegistry.session()` 시그니처는 바꾸지 않는다.
- **가림이 예외를 내면** 원문을 보내지 않는다. 필터가 `_Stop("provider_error", "입력 가림에 실패해 보내지 않았다")`을 낸다. 예산 초과(`budget_exceeded`)와 같은 길이라 `finalize`가 `sent=false` 종료 줄을 남긴다. 도구 호출은 이미 끝났으므로 그 호출 하나만 실패 처리하는 것이 아니라 run이 `provider_error`로 끝난다. 이 점이 "호출 failed"를 가장 가깝게 옮긴 것이다.
- **근거 ID 모양 값은 가림에서 건너뛴다.** 입력이 JSON 문자열이라 레지스트리의 `id_fields`를 필터에서 알 수 없다. 대신 `soc.ids.PREFIXES`의 접두사 + UUIDv7 모양 문자열을 가림에서 제외한다(그 값은 모든 규칙에서 건너뜀). `id_fields`·`allowed_evidence_ids`·`call_id`(`agl_`)가 모두 이 모양이라 같은 효과다. 짧은 환경변수 값이 UUID 조각과 겹쳐 근거 장부 ID를 바꾸는 일을 막는다.

### C1-B. 도구 쪽에서 비밀이 나올 자리를 빼지 않는다 (후보 A)

- `ssh.py`의 `processes`(`ps -eo pid,ppid,user,etime,args`)와 D-011 메모, `authorized_keys`의 `command=` 예시는 그대로다. 명령줄 인자는 L1·L2가 가장 필요로 하는 신호다.
- `query_siem`은 `TARGET_FIELDS` 허용 목록만 돌려주고 `authorization` 칸이 없다. 도구 쪽 제거는 이미 되어 있어 할 일이 없다.
- 남는 위험은 `docs/security.md`에 적는다(아래 "한계").

### 가림 규칙 (후보 B: 확실한 모양만 추가)

`src/soc/agent/redact.py`. 지금 규칙(환경변수 값, DB 주소 비밀번호, URL 속 비밀번호, `password=`·`api_key`·`Bearer`, 객체 키)에서 아래를 바꾼다. 정규식의 정확한 모양은 개발 때 정한다.

| 규칙 | 바뀌는 것 |
|---|---|
| `pwd` | 값이 `/`로 시작하면 건너뛴다(sudo `PWD=/home/alice`). `?pwd=secret`과 ODBC `PWD=`는 계속 가린다 |
| 환경변수 값 | 최소 길이 4 → 8(`_MIN_SECRET_LENGTH`). 여러 줄 값의 줄 단위 가림도 같은 길이를 쓴다 |
| `token`·`secret` | 이름이 `token`·`secret`으로 끝나는 낱말(`token`, `access_token`, `client_secret`, `refresh-token`)의 `=`·`:` 값(JSON `"key":"값"` 모양 포함) |
| `Authorization` | `Authorization` 뒤 `:`·`=`·JSON 문자열 속의 `Basic`·`ApiKey` 값. 이미 있는 `Bearer`는 그대로 |
| 객체 키 | `_SECRET_KEYS`에 `token`·`secret` 계열 키 이름을 더할지는 개발 때 정한다(문자열 규칙으로 막히는지 보고) |

넣지 않는 것: 명령줄 모양(`--password 값`, `-pSECRET`). 오탐이 커서 후속으로 둔다.

### C9. 표시는 남기지 않는다 (후보 A)

- Agent Log에 `details.redacted` 같은 표시를 만들지 않는다. 입력 줄과 도구 줄은 모델이 받은 입력과 같고, `[REDACTED]` 문자열이 그대로 표시다.
- 남는 차이(모델 출력 줄, `details`, 도구 인자 줄은 쓰기 직전에만 가려 모델이 낸 원문과 다를 수 있음)는 `docs/security.md`와 D-036 메모에 적는다. `agent_log` 계약은 바꾸지 않는다.

### 문서

- `docs/security.md`에 "모델 입력(외부 LLM으로 보내는 내용)" 절을 만든다. 적을 것:
  - 가림은 SDK 입력 필터 한 곳에서 하고, 가리는 모양과 가림 중 예외가 나면 보내지 않는 것
  - **한계**: 8자 미만 비밀은 못 가린다. 알려진 모양만 가린다(`--password 값`·`-pX` 명령줄, 이름·값 쌍 헤더 `{"name":"Authorization","value":"Basic ..."}`는 못 가림). 이미 잘려 조각난 환경변수 값은 못 가린다. SSH `processes`의 명령줄에 비밀이 있으면 알려진 모양 밖에서는 외부 LLM으로 나간다(#213 기록의 위험을 그대로 둔다). 모델이 낸 출력은 입력을 거친 값이지만 별도로 가리지 않고 파이프가 저장한다
  - 과잉 가림은 모델의 증거를 가린다. 공격자가 `password=<덩어리>` 모양을 넣으면 그 덩어리가 모델에게도 보이지 않는다
  - 가림 뒤에도 Agent Log와 모델 출력의 차이(위)
- `docs/decisions.md`: D-048 추가, D-036 메모의 복원 설명을 맞춘다(이 계획과 같은 커밋).

### 위험

- **#280과 충돌한다.** #280(C4: 동기 도구가 이벤트 루프를 막음)도 `src/soc/agent/runner.py`·`src/soc/tools/registry.py`를 고친다. 머지 순서는 이슈 담당자가 팀과 정해 알린다. 이 계획은 `registry.py`를 고치지 않지만 `runner.py`의 `_execute`·`_writer`는 겹친다.
- **판정 품질이 달라질 수 있다.** 모델이 `[REDACTED]`를 본다. 실제 모델로 확인하지는 않는다(기본 테스트·CI는 가짜 모델).
- 8자 미만 비밀을 못 가리는 것은 알려진 한계로 받아들인다.
- 필터는 SDK의 `ModelInputData` 항목 모양(dict)에 기대므로 SDK 버전이 바뀌어 항목 모양이 달라지면 가림이 빠질 수 있다. 완료 기준 테스트가 `FakeModel.calls`로 막는다.

## 바꿀 곳

- `src/soc/agent/redact.py`: 규칙 변경, ID 모양 건너뛰기, 항목 단위 호출
- `src/soc/agent/runner.py`: 입력 필터가 가림을 적용, 가림 실패 시 `_Stop`, 가림 함수를 `run_task`에서 한 번 만들어 `RowWriter`와 공유
- `tests/test_agent_redact.py`, `tests/test_agent_core.py`, `tests/test_agent_log_durability.py`: 새 규칙·입력 필터 테스트. 기존 테스트 중 4글자 비밀 값이나 필터 전 입력을 기대하는 것을 고친다
- `tests/fixtures/agent/redact_samples.json`(위치는 개발 때 정함): 정상 문자열과 비밀 모양 샘플. 모두 가짜 값과 문서용 IP
- `docs/security.md`, `docs/decisions.md`(D-048, D-036 메모), `docs/notes/279-llm-input-redaction.md`(개발 기록)

## 다른 코드와 맞물리는 곳

| 바꾸는 것 | 읽는 곳 · 담당 |
|---|---|
| 모델에게 가는 입력이 가림을 거친다. 모델이 `[REDACTED]`를 볼 수 있다 | L1·L2·L3 프롬프트·판정(`soc.l1`·`soc.l2`·`soc.l3`) 담당 |
| Agent Log model 줄 `input`과 `records` 도구 줄 `output`이 가림 적용 후 값이다(원문 아님) | Agent Log를 읽는 곳(`hunts.py`, 화면). 읽는 규칙은 같다 |
| 환경변수 값 가림 최소 길이 4 → 8 | 테스트의 가짜 비밀 값 |
| D-048 추가, D-036 메모 | 팀 전체 |
| `runner.py` `_execute`·`_writer` 변경 | #280 담당(충돌 위험, 위) |

설정 키·테이블·계약·환경변수는 바꾸지 않는다. `.env.example` 변경 없음.

## 범위 밖

- 명령줄 모양(`--password 값`, `-pX`) 가림, 이름·값 쌍 헤더 가림
- `processes` 명령줄 인자 제거, SIEM 결과 필드 변경(이미 `authorization`은 없음)
- 모델 출력(`AgentResult.output`)을 저장하기 전에 가리기
- Agent Log `details.redacted` 표시, `agent_log` 계약 변경(`details` 설명 문구 정리는 #278이 남긴 후속)
- 실제 모델로 판정 품질을 비교하는 것
- #280 C4(동기 도구가 이벤트 루프를 막음)

## 완료 기준

- [ ] (C1) 가짜 모델 입력(`FakeModel.calls`)에 비밀 모양 값이 없다. 값 모양은 환경변수 값(8자 이상), `password=`·`token=`·`Authorization: Basic`이다. 위치는 도구 결과 세 종류(`records`·`text`·`aggregate`), `task.data`, 형식 오류 재요청이다. Agent Log 줄도 같다.
- [ ] (C1) 같은 `run_id`의 model 줄 `input`을 이어 붙여 복원한 입력이 모델이 받은 입력(`FakeModel.calls`)과 같다. `input_reset`이 생기지 않는다.
- [ ] (C1) **같은 입력 이력이면 필터는 항상 같은 결과를 낸다.** 여러 턴과 형식 오류 재요청에서 앞 호출 입력의 가림 결과가 다음 호출 입력의 가림 결과의 접두이고, 가림을 두 번 적용해도 결과가 같다.
- [ ] (C1) 가림이 예외를 내면 모델이 호출되지 않고(`FakeModel.calls`에 그 입력이 없음), run은 `provider_error`로 끝나며 `sent=false` 종료 줄이 남는다.
- [ ] (C1) 환경변수 값이 근거 ID 조각과 겹쳐도 `agl_`·`alt_`·`evt_` ID가 바뀌지 않고, 근거 장부 인용(`evidence_id_error` 없음)이 통과한다.
- [ ] (C1) 도구 쪽은 바뀌지 않는다: `processes` 명령·결과 필드, `query_siem` 필드 목록이 그대로다(기존 테스트 통과).
- [ ] (C9) `tests/fixtures/`의 정상 문자열 샘플이 바뀌지 않는다: sudo `auth.log` 줄의 `PWD=/home/alice`, 환경변수 값이 `admin`일 때 `user.name: admin`(8자 미만이라 가리지 않음).
- [ ] (C9) 비밀 모양 샘플이 가려진다: `url.query`의 `token=`·`access_token=`, `Authorization: Basic` 헤더, `?pwd=secret`.
- [ ] (C9) 8자 미만 환경변수 값은 가리지 않음을 테스트로 고정한다(한계).
- [ ] 샘플은 모두 가짜 값과 문서용 IP(`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`)다.
- [ ] `docs/security.md`에 모델 입력 절(가림 범위, 한계, 남는 차이), `docs/decisions.md`에 D-048과 D-036 메모가 있다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과(db·화면 마커 테스트는 CI). `scripts/generate_contracts.py --check`는 계약을 바꾸지 않으므로 변화 없음을 확인한다.
- [ ] 새 환경변수는 없다(`.env.example` 변경 없음).
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록이 있다.

## 토론으로 정한 것

이슈의 "정하지 못함" 두 개와 검토에서 나온 질문의 답이다.

**원래 이슈와 달라진 점**
- 이슈의 후보 중에서 골랐다: C1은 SDK 입력 필터 한 곳(B), 도구 쪽 제거는 하지 않음(A), C9는 좁히기(A)와 표시 없음(A).
- 이슈 C1-A는 "레지스트리가 모델에게 돌려주기 전에 가린다"였다. 이슈에 없던 `task.data`(첫 사용자 메시지)도 모델 입력이라 함께 가리도록 SDK 입력 필터 한 곳으로 정했다. 레지스트리·`ToolRegistry.session()` 시그니처는 바꾸지 않는다.
- 이슈에 없던 가림 규칙 추가가 들어왔다: `token`·`secret`·`access_token`, `Authorization: Basic|ApiKey`. 모델 입력까지 가리면 미탐이 바로 외부 유출이라서다. 명령줄 모양은 오탐이 커서 제외했다.
- 이슈의 C1-B "SIEM `authorization` 칸을 반환 필드에서 빼기"는 이미 되어 있다(`query_siem`은 허용 목록만 돌려줌).
- 환경변수 값 최소 길이 4 → 8. 흔한 낱말(`admin`)이 정상 로그를 가리는 것을 줄이는 대가로 8자 미만 비밀은 못 가린다.

**질문과 답**
1. (C1) 가림 위치: **B SDK 입력 필터 한 곳.** `task.data`·도구 결과·재요청을 한 번에 덮고 `ToolRegistry.session()` 시그니처를 바꾸지 않으며, 로그의 model 줄이 보낸 입력과 같아진다. 키 규칙이 JSON 문자열 속에서 안 도는 것은 `authorization`을 문자열 규칙으로 더해 메운다. 잘린 조각은 한계로 문서화한다.
2. (C1-B) 도구 쪽 제거: **A 하지 않음.** `processes` 인자를 빼면 L1·L2의 핵심 신호를 잃고 D-011을 고쳐야 한다. 잔여 위험은 `docs/security.md`에 적는다.
3. 가림 규칙 확대: **B 확실한 모양만 추가.** `token`·`secret`·`access_token`의 `=`·`:` 값, `Authorization: Basic|ApiKey`.
4. (C9-A) 좁히기: **`pwd` 값이 `/`로 시작하면 건너뜀 + 환경변수 값 최소 길이 4 → 8.** 8자 미만 비밀은 못 가린다는 한계를 `security.md`에 적는다.
5. (C9-B/C) 표시: **A 표시 없음.** 입력·도구 줄은 모델 입력과 같고 `[REDACTED]`가 표시다. 남는 차이는 `security.md`와 D-036 메모에 적는다.

**빈칸에서 정한 것**
- 가림 중 예외가 나면 원문을 보내지 않고 실패로 둔다. 구현은 필터의 `_Stop("provider_error")`다.
- 근거 ID 필드는 가림에서 건너뛴다. 필터는 문자열만 보므로 ID 접두사 + UUIDv7 모양 문자열을 건너뛰는 방식으로 옮겼다.
- 필터는 같은 입력 이력이면 항상 같은 결과를 내야 하고, 이것을 완료 기준 테스트에 넣는다.
- #280과의 충돌은 위험 항목에만 적는다. 머지 순서는 이슈 담당자가 팀과 정해 알린다.
- 샘플은 4가지(sudo `auth.log` `PWD=`, `user.name admin`과 환경변수 값 `admin`, `url.query` 토큰, `Authorization: Basic` 헤더), 모두 가짜 값과 문서용 IP를 쓴다.

**결정 목록에 올린 안건**: D-048(모델 입력 가림)을 추가했고 D-036 메모의 복원 설명을 맞췄다. 팀 공유가 필요하다.

## 바뀐 점
