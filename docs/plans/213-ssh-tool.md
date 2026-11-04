---
issue: 213
date: 2026-11-05
owner: Interludeal
supersedes: []
---

# SSH 호스트 점검 도구 만들기

## 목표

`src/soc/tools/ssh.py`에 `run_host_check`를 asyncssh로 #211 레지스트리(`ToolSpec`) 위에 만들고, L2·L3에서만 쓰게 한다.
모델은 설정에 이름을 붙인 호스트와 코드에 정해진 점검 5개, 허용 문자만 받는 인자만 고르고, 명령 문자열과 접속 주소는 쓰지 못한다.
설정의 호스트 키로만 검증해 접속하고, 결과는 구분자로 감싸 `call_id`로만 인용하며, 아래 완료 기준이 실제 원격 호스트 없이 테스트로 확인되면 끝이다.

## 방법

결정 반영(이 계획의 확정 커밋에서 함)

- `docs/decisions.md` 확정에 D-041을 더한다: SSH 라이브러리 asyncssh(`asyncssh==2.24.1`). 메모: 라이선스 EPL-2.0 OR GPL-2.0-or-later이고 수정 없이 import만 한다. 버전은 고정하고 함께 들어오는 패키지는 `uv.lock`으로 고정한다(`cryptography`는 이미 50.0.2로 들어 있다). 팀 합의(L1·L2·L3 담당, #213).
- D-011 메모의 "원격 셸 해석을 막는 구체 방법은 이 이슈에서 정한다"를 아래 "인자 검사"로 채운다. `authorized_keys`의 `command=` 제한은 운영자가 더할 수 있는 두 번째 방어선으로 기록에만 적는다.
- `docs/security.md` "에이전트 도구의 한계"의 "구체 방법은 SSH 도구(D-011) 이슈에서 정한다"를 D-011 메모를 가리키게 고친다.
- 기록 줄: "팀 합의(#213)".

도구 모양

- `run_host_check(host, check, count, lines, path)`. `host`·`check`는 필수, `count`·`lines`·`path`는 선택(strict일 때 #211처럼 "required + null 허용").
- `host`: 설정 `[[tools.ssh.hosts]]`의 `name` 중 하나(enum, 아래 `configure`). 목록 밖은 접속 전에 `invalid_argument`.
- `check`: 코드 상수 5개 중 하나(enum). 그 호스트의 `checks`에 없는 점검을 고르면 접속 전에 `invalid_argument`.
- 고른 점검이 받지 않는 인자에 값이 들어오면 `invalid_argument`(`ToolSpec.check`).

점검(코드 상수, 모두 읽기 명령이고 파이프·리다이렉트·세미콜론이 없다)

| 점검 | 명령 | 인자 |
|---|---|---|
| `processes` | `ps -eo pid,ppid,user,etime,args --no-headers` | 없음 |
| `listening_ports` | `ss -tuln` | 없음 |
| `recent_logins` | `last -F -n <count>` | `count`: 정수 1~50, 기본 20 |
| `auth_log_tail` | `tail -n <lines> /var/log/auth.log` | `lines`: 정수 1~200, 기본 50. 경로는 상수 |
| `file_hash` | `sha256sum -- <path>` | `path`: 절대 경로, 필수 |

- 설정은 어느 호스트에서 어느 점검을 켤지만 정한다(D-011의 "허용 명령은 설정 값"). 설정에서 명령 문자열을 받지 않는다.
- 배포판마다 옵션이 다르면(예: Debian 13의 wtmpdb `last`) 계획 "바뀐 점"에 고치고 이유를 적는다.

인자 검사(D-011 메모를 채우는 구체 방법)

- 허용 문자만 받는다(화이트리스트).
- 정수는 범위만 본다.
- `path`는 `/`로 시작하고 `[A-Za-z0-9._/-]`만 쓰며 256자 이하. `..` 구간, 연속 `/`, 끝의 `/`는 받지 않는다.
- 모든 인자 값(정수는 문자열로 바꾼 값)이 `-`로 시작하면 거부한다. 같은 함수로 검사한다.
- 통과한 값도 `shlex.quote`로 감싸서 명령에 넣는다. 정수도 문자열로 바꾼 뒤 감싼다.
- `/dev/zero` 같은 경로는 막지 않고 명령 timeout으로 끝낸다(`/proc/<pid>/exe` 해시는 쓸모가 있다).
- 원격 계정의 로그인 셸은 POSIX sh 계열이어야 `shlex.quote`가 맞다(기록에 적는다).

호스트를 모델에게 보이는 법(레지스트리 변경, 원칙 7)

- `ToolSpec`에 선택 칸 `configure(tools_config) -> ToolSpec | None`을 더한다. `ToolRegistry.session()`이 `check_config` 다음에 부른다.
- `run_host_check`의 `configure`는 설정의 호스트 이름을 `host` enum에, 호스트별 켜진 점검을 설명에 넣은 `ToolSpec`을 돌려준다. 호스트가 하나도 없으면 `None`이고, 그 실행에서 도구를 등록하지 않는다(모델에게 보이지 않음).
- 등록하지 않은 도구를 레지스트리 함수로 직접 부르면 #211처럼 `not_allowed`다.
- 칸이 없는 도구는 동작이 그대로다(#211·#212 테스트로 확인).

설정(`config/default.toml`)

- `[tools.ssh]`: `key_env = "SSH_TOOL_PRIVATE_KEY"`, `passphrase_env = ""`(선택, 빈 문자열이면 안 씀), `connect_timeout_seconds = 5`, `command_timeout_seconds = 10`, `deadline_seconds = 15`, `max_output_bytes = 65_536`, `max_stderr_chars = 2000`.
- `[[tools.ssh.hosts]]`: 칸은 `name`, `address`, `port`(기본 22), `username`, `host_key`(공개 호스트 키 한 줄, 예: `ssh-ed25519 AAAA…`), `checks`(켤 점검 이름 목록). default.toml에는 빈 목록(`hosts = []`)과 주석 예시만 둔다. 실제 값은 `config/local.toml`(커밋 안 함).
- `name`은 `[a-z0-9][a-z0-9-]{0,62}`. 모델에게 보이므로 주소·계정을 넣지 않는다(주석).
- 키 파일 경로는 설정에 두지 않는다. 키는 `key_env`가 가리키는 환경변수의 OpenSSH 개인 키 본문만 쓴다.
- `[tools.allowed]`: l2·l3에 `run_host_check`를 더한다. l1에는 넣지 않는다.
- `.env.example`: `SSH_TOOL_PRIVATE_KEY`, `SSH_TOOL_KEY_PASSPHRASE` 이름만.

설정 검사

- `check_config`(모양만, #212와 같다): `[tools.ssh]`가 표가 아님, `hosts`가 목록이 아님, 이름 없음·형식 틀림·중복, `checks`에 코드에 없는 점검 이름 → `provider_error`.
- address·port·username·host_key 형식, timeout·크기 값, 환경변수는 호출할 때 본다(아래 오류 표).

접속(asyncssh)

- 호출마다 새로 접속한다. `asyncio.timeout(deadline_seconds)`로 호출 전체를 감싼다(D-039와 같은 뜻).
- `known_hosts`에는 설정의 `host_key` 하나만 넣는다. TOFU는 없다. host_key가 없거나 형식이 틀리거나 맞지 않으면 접속하지 않는다.
- asyncssh 기본값을 끄고 명시한다: `config=None`(`~/.ssh/config` 안 읽음), `agent_path=None`, `client_keys=[환경변수 키]`, `known_hosts=<설정 host_key만>`, `password=None`, `kbdint_auth=False`, `x509_trusted_certs=None`, `preferred_auth="publickey"`, `connect_timeout`. `~/.ssh`의 키·known_hosts가 쓰이지 않음을 테스트한다.
- 명령은 `create_process(..., encoding=None)`로 실행하고 `command_timeout_seconds`를 둔다. `conn.run()`은 출력을 모두 모으므로 쓰지 않는다.

출력

- stdout은 `max_output_bytes`까지만 읽는다. 넘으면 거기서 끊고 결과에 `stdout_truncated: true`를 붙인다(오류 아님).
- stderr도 같은 바이트 상한까지 읽고, 결과에는 앞 `max_stderr_chars`자만 담는다.
- UTF-8로 풀되 깨진 바이트는 대체 문자로 바꾼다. 제어 문자는 `\n`·`\t`만 남기고 지운다(ANSI 이스케이프, `\r` 포함).
- 종료 코드가 0이 아니어도 `TOOL_ERROR`가 아니다. 신호로 끝나 종료 코드가 없으면 `exit_status: null`과 `exit_signal`.

결과(`result_kind = "aggregate"`)

- 모양: `{"call_id", "source": "ssh", "host", "check", "exit_status", "exit_signal", "stdout", "stdout_truncated", "stderr", "truncated"}`.
- 한도(`max_tool_result_chars`)는 핸들러가 `ctx.fits`로 맞춘다. stdout을 먼저, 그다음 stderr를 줄이고 `"truncated": true`를 붙인다. 기본은 앞쪽을 남기고, `auth_log_tail`은 최신 줄이 있는 끝쪽을 남긴다.
- 결과 전체는 #211처럼 `<tool_result>`로 감싸고 `<`·`>`를 바꿔 탈출을 막는다. 장부에는 `call_id`만 들어간다. 출력 속 `alt_` 모양 문자열을 인용하면 `evidence_id_error`.
- 결과와 Agent Log `details`에는 host 이름과 check 이름만 적는다. address, username, 조립한 명령 원문은 넣지 않는다.

오류

| 상황 | 코드 | `details.reason` |
|---|---|---|
| 키 환경변수 없음, 키를 읽지 못함, address·port·username·timeout 설정 값 틀림 | `unavailable` | `config` |
| 접속 실패(연결 거부, 이름 풀이, 끊김) | `unavailable` | `network` |
| connect·명령 timeout, `deadline_seconds` 초과 | `timeout` | 없음 |
| 인증 실패 | `failed` | `auth` |
| host_key 없음·형식 틀림·불일치 | `failed` | `host_key` |

- 모델에게는 #211의 `TOOL_ERROR` 문구만 간다. 예외 메시지, 주소, 계정, 키는 모델·`detail`·Agent Log `details`에 넣지 않는다.
- 연속 2회 차단, 오류·차단 호출은 장부에 없음은 #211 그대로다.

레지스트리 비동기 핸들러(레지스트리 변경, 원칙 7)

- `ToolSession.invoke`(이미 `async`)에서 `raw = spec.handler(args, ctx)` 뒤에 awaitable이면 await한다. 동기 핸들러는 그대로다. 별도 스레드 루프는 쓰지 않는다.

비밀 값

- `build_redactor`가 설정 전체의 `*_env`를 보므로 `key_env`·`passphrase_env` 값은 가려진다. 개인 키처럼 여러 줄인 값이 통째로 가려지는지 테스트를 더한다. `redact.py`는 테스트가 실패할 때만 고친다.

테스트

- 실제 원격 호스트에는 접속하지 않는다.
- 접속 없는 단위 테스트: 인자 검사, 설정 검사, 명령 조립(`shlex.quote` 결과). 셸 특수문자(`;` `|` `&` `$` `` ` `` `>` `<` `(` `)` 줄바꿈, 공백, 따옴표, `..`)와 `-`로 시작하는 값을 모두 넣는다.
- 호스트 키 검증과 실행 흐름은 테스트 안에서 127.0.0.1에 띄운 asyncssh 서버로 확인한다. 테스트 키는 실행 중에 만들고 커밋하지 않는다. 서버는 정해진 명령에 정해진 출력만 돌려준다(`tests/fixtures/ssh/`의 손으로 만든 출력). CI에서 안 되면 가짜 연결 주입으로 바꾸고 이유를 적는다.
- 가짜 모델로 "`run_host_check` 호출 → 그 `call_id`를 근거로 한 Verdict"가 장부 검사를 통과하는지, 출력 본문 속 `alt_` 문자열을 인용하면 막히는지 확인한다.
- 실제 데모 호스트 테스트는 `ssh` 마커로 나눠 기본 실행과 CI에서 뺀다. 사람이 PC에서 돌린다.

## 바꿀 곳

- `docs/decisions.md`: D-041 추가, D-011 메모, 기록 줄(확정 커밋)
- `docs/security.md`: "에이전트 도구의 한계"의 구체 방법 문장(확정 커밋)
- `pyproject.toml`·`uv.lock`: `asyncssh==2.24.1`, `ssh` 마커와 `addopts`
- `src/soc/tools/ssh.py`: 점검 상수, 인자 검사, 명령 조립, 설정 검사, `configure`, 접속·실행, 결과 모양, `RUN_HOST_CHECK`
- `src/soc/tools/registry.py`: awaitable 핸들러, `ToolSpec.configure`와 `session()`
- `src/soc/tools/__init__.py`: 운영 레지스트리에 추가
- `config/default.toml`: `[tools.ssh]`, `hosts = []`와 주석 예시, `[tools.allowed]` l2·l3
- `.env.example`: `SSH_TOOL_PRIVATE_KEY`, `SSH_TOOL_KEY_PASSPHRASE`
- `tests/`: SSH 도구 테스트, 가짜 SSH 서버 도우미, `tests/fixtures/ssh/`, 레지스트리 테스트(awaitable·configure), 가림 테스트, `ssh` 마커 테스트

## 다른 코드와 맞물리는 곳

- **`ToolSpec`에 선택 칸 `configure`가 생긴다.** 허용 목록에 있어도 `configure`가 `None`이면 그 실행에서 등록하지 않는다. #211의 "허용 목록에 있으면 등록"에 예외가 하나 생긴다. 칸이 없는 도구는 그대로다. #214가 쓸 수 있다.
- **핸들러가 awaitable을 돌려줄 수 있다.** 동기 핸들러는 그대로다.
- **운영 레지스트리에 도구 1개가 늘고 `[tools.allowed]` l2·l3 기본값이 바뀐다.** 기본 설정은 호스트가 비어 있어 등록되지 않는다.
- **새 설정 키**: `[tools.ssh]`(`key_env`, `passphrase_env`, `connect_timeout_seconds`, `command_timeout_seconds`, `deadline_seconds`, `max_output_bytes`, `max_stderr_chars`, `hosts`).
- **새 환경변수 이름**: `SSH_TOOL_PRIVATE_KEY`, `SSH_TOOL_KEY_PASSPHRASE`.
- **새 의존성**: `asyncssh==2.24.1`(D-041).
- **#214와 같은 파일을 고친다**: `config/default.toml`의 `[tools.allowed]`, `.env.example`, `pyproject.toml` 마커, `registry.py`. 나중에 머지하는 쪽이 rebase한다.
- **L2 분석(L2-B, 아직 이슈 없음)**: l2 실행에 이 도구가 붙는다. L2 담당에게 알린다.

## 범위 밖

- `authorized_keys`의 `command=` 강제 명령 → 운영자가 더할 수 있는 두 번째 방어선, 기록에만 적는다
- 접속 재사용(연결 풀) → 필요해질 때
- 설정으로 점검 늘리기, RHEL 계열(`/var/log/secure`) 점검 → 필요해질 때
- 데모 호스트 만들기 → 사람이 한다(방법만 기록에 적는다)
- L2 분석 프롬프트에 사용법 넣기 → L2 담당

## 완료 기준

- [ ] D-041(asyncssh)이 `docs/decisions.md` 확정에 있고, D-011 메모가 채워졌다
- [ ] `run_host_check`가 l2·l3 허용 목록에 있고 l1에는 없다. L1 실행에는 등록되지 않는다(모델에게 보이지 않음)
- [ ] 레지스트리 함수를 목록 밖에서 직접 부르면 `not_allowed`
- [ ] 설정에 호스트가 없으면 등록되지 않고, 직접 불러도 접속하지 않는다
- [ ] 설정에 있는 호스트 이름만 `host` enum과 설명에 나온다
- [ ] 목록 밖 host, 목록 밖 check, 그 호스트에서 켜지 않은 check, 점검에 맞지 않는 인자, 셸 특수문자·`..`·연속 `/`·끝 `/`·`-`로 시작하는 값·범위 밖 정수 → 접속 전에 `invalid_argument`
- [ ] 조립한 명령의 인자가 모두 `shlex.quote`로 감싸져 있다(정수 포함)
- [ ] 설정에 코드에 없는 점검 이름이나 중복 호스트 이름이 있으면 `provider_error`
- [ ] host_key가 맞지 않거나 없으면 접속하지 않는다(`failed`, `details.reason=host_key`). `~/.ssh`의 known_hosts·키·config는 쓰이지 않는다
- [ ] 테스트 asyncssh 서버(127.0.0.1)로 점검 5개가 정해진 출력을 돌려준다
- [ ] 종료 코드가 0이 아니면 `exit_status`와 stderr 앞부분이 결과에 있고 오류가 아니다
- [ ] stdout이 `max_output_bytes`를 넘으면 끊고 `stdout_truncated: true`. 한도를 넘으면 `truncated: true`, `auth_log_tail`은 끝쪽을 남긴다
- [ ] 깨진 UTF-8은 대체 문자, 제어 문자(ANSI 포함)는 지워진다
- [ ] 키 없음 → `unavailable`(`config`), 접속 실패 → `unavailable`(`network`), 시간 초과·마감 초과 → `timeout`, 인증 실패 → `failed`(`auth`)
- [ ] 결과 본문의 `</tool_result>`가 구분자를 닫지 못한다
- [ ] `call_id`를 근거로 한 Verdict가 장부 검사를 통과하고, 출력 속 `alt_` 문자열을 인용하면 `evidence_id_error`(가짜 모델)
- [ ] 개인 키·암호·address·username·명령 원문이 모델 입력·`detail`·Agent Log `details`에 없다. 여러 줄 개인 키가 Agent Log에서 통째로 가려진다
- [ ] 동기 핸들러와 `configure` 칸이 없는 도구의 동작이 그대로다. #211·#212 테스트를 지우거나 건너뛰지 않았다
- [ ] 실제 데모 호스트 테스트는 `ssh` 마커로 기본 실행·CI에서 빠진다
- [ ] `.env.example`에 새 환경변수 이름만 있다
- [ ] `docs/notes/`에 `ssh` 마커 실행 방법, 데모 호스트 읽기 전용 계정 만드는 법(adm 그룹, POSIX 셸, sshd·procps·iproute2·rsyslog), 여러 줄 키를 환경변수에 넣는 법, `command=` 두 번째 방어선, `processes` 출력의 비밀 노출 위험, `configure`·awaitable(#214)을 적었다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

이슈 본문과 달라진 점

- **SSH 라이브러리 asyncssh 결정(D-041)은 이 이슈에서 한다.** 본문의 "개발 레포 반영은 #209"는 틀렸다. 팀 합의를 받았다(L1·L2·L3 담당, #213).
- **담당.** 본문의 "정하지 못함: 누가 만들지"는 정했다. 에이전트 계층 도구 묶음으로 두고 담당은 Interludeal이다. L2 담당에게 알린다.
- **L1.** 본문 완료 기준 "L1에서는 `not_allowed`"는 #211 결정에 맞춰 "L1에는 등록되지 않는다. 레지스트리 함수를 목록 밖에서 직접 부르면 `not_allowed`"로 바꾼다.
- **#211·#212에서 정해진 것을 따른다.** `ToolSpec`·레지스트리, `check_config`, `TOOL_ERROR` 문구, `details.failure` 코드 5개와 `details.reason`, 연속 2회 차단, 결과 자르기, `call_id` 하나, 오류·차단 호출은 장부에 없음.
- **결과 종류는 `text`가 아니라 `aggregate`다(질문 2).** 인용은 그대로 `call_id`로만 한다. #211 계획의 "text는 SSH 도구가 쓴다"와 다르다.

미리 정한 답(사람이 검토 전에 정함)

- A. 모델은 주소·명령 문자열을 쓰지 않는다. host는 설정 이름, check는 코드 이름, 목록 밖은 접속 전 `invalid_argument`.
- B. 점검 5개의 명령과 인자 모양은 코드 상수, 설정은 켤 점검만, 기본은 호스트가 비어 전부 거부.
- C. 화이트리스트 인자 검사, `-`로 시작하는 값 거부, `shlex.quote`. D-011 메모를 채운다. `command=`는 기록에만.
- D. `[[tools.ssh.hosts]]` 칸, `config/local.toml`, `key_env`(`SSH_TOOL_PRIVATE_KEY`)·`passphrase_env`, 키 파일 경로 없음.
- E. 설정 host_key로만 검증, TOFU 없음, 틀리면 `failed`(`host_key`).
- F. 호출마다 접속, connect 5초·명령 10초·마감 15초, 64KB, 대체 문자, 제어 문자 제거, 0이 아닌 종료 코드는 오류 아님, 오류 대응 표.
- G. awaitable 핸들러를 await하도록 레지스트리를 고친다.
- H. 단계 허용 l2·l3.
- I. 비밀 값을 오류·detail·Agent Log에 넣지 않음, `*_env` 가림 확인, 여러 줄 키 테스트.
- J. 실제 호스트 없음, 단위 테스트, 127.0.0.1 asyncssh 서버, `ssh` 마커, 기록에 실행·계정 만드는 법, 가짜 모델 Verdict.

검토에서 정한 것

- **질문 1: B.** stdout이 64KB를 넘으면 끊고 `stdout_truncated: true`를 붙인다(오류 아님). 모델은 어차피 `max_tool_result_chars`까지만 보고, 실제 서버의 `ps`는 64KB를 넘기 쉬워서다. F 오류 표의 `failed`(`too_large`)는 빠진다.
- **질문 2: A.** `aggregate`로 `{host, check, exit_status, stdout, stderr, …}`를 따로 칸에 둔다. text 결과는 문자열 칸 하나라 메타 값을 stdout에 섞으면 공격자가 위조할 수 있기 때문이다. 레지스트리의 결과 종류는 바꾸지 않는다.
- **질문 3: B.** `ToolSpec.configure`로 설정의 호스트 이름을 enum과 설명에 넣고, 호스트가 없으면 등록하지 않는다. 정적 enum으로는 배포마다 다른 호스트를 모델에게 알릴 수 없고, 추측하게 두면 두 번 만에 차단되기 때문이다.
- **질문 4: A.** `args` 객체 대신 평평한 선택 인자 `count`·`lines`·`path`. `Arg`가 객체를 표현하지 못하기 때문이다(#212 질문 1과 같다).
- **asyncssh 기본값을 끈다.** `~/.ssh/config`·known_hosts·키·에이전트를 기본으로 읽으므로 모두 명시한다.
- **출력은 `create_process`로 나눠 읽는다.** `conn.run()`은 바이트 상한을 지킬 수 없다.
- **`docs/security.md`의 구체 방법 문장을 D-011 메모를 가리키게 고친다.**
- **빈칸 기본값을 그대로 쓴다.** `check_config`는 모양만, 켜지 않은 점검은 `invalid_argument`, 제어 문자는 `\n`·`\t`만 남김, stderr 2,000자, 신호 종료는 `exit_status: null`과 `exit_signal`, `/dev/zero` 같은 경로는 timeout으로, `details`에 주소·계정·명령 원문 없음, `ssh` 마커, 호스트 이름 형식 `[a-z0-9][a-z0-9-]{0,62}`.

## 바뀐 점

- 2026-11-05 · 암호가 걸린 OpenSSH 형식 개인 키는 지원하지 않는다(그런 키는 `unavailable`, reason `config`). asyncssh가 그 암호를 풀려면 bcrypt(선택 패키지)가 필요한데 확정된 라이브러리가 아니기 때문이다. `passphrase_env`는 암호가 걸린 PKCS#8 PEM 키에만 쓴다. 데모 키는 암호 없이 만든다. 필요해지면 bcrypt를 결정 목록 안건으로 올린다. 사람이 확정함
