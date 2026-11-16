---
issue: 321
date: 2026-11-16
owner: Juhyeok0603
plan: 321-incident-graph-ui.md
supersedes: []
---

# Incident 상세에서 공유 엔티티 연결을 한 관계도로 읽는다

## 한 일

- Incident 상세의 Ticket별 가로 경로 목록을 하나의 관계도로 바꿨다. 현재 Incident에 이어지는 저장 경로만 모으고 공유 Entity·중복 연결선을 합친다. Incident 소속선과 공유 엔티티 연결선은 다른 색과 범례로 구분한다.
- Ticket별 분류 당시 탐색 상태와 경로별 텍스트 설명을 관계도 뒤에 표시한다. 첫 Ticket의 자기 분류 기록에 경로가 없어도 후속 Ticket이 저장한 경로에서 연결될 수 있다.
- 공유 엔티티 연결선 가운데에 엔티티 종류·값을 SVG 텍스트로 적었다. 선 하나만 봐도 무엇을 공유해 이어졌는지 읽히게 하기 위해서다. 엔티티에 닿는 저장 경로 선에만 붙고 소속선과 Ticket-기록 선에는 붙지 않는다. svg는 `aria-hidden`을 유지해 보조기기에 중복 낭독되지 않는다.
- 키보드로 초점을 옮기고 스크롤할 수 있는 관계도와 텍스트 대체 경로를 넣었다. 화면 값은 React 텍스트로만 그리며 기존 원본 링크의 권한 검사를 유지한다.
- 손으로 만든 프론트엔드 fixture에 공유 Entity, Alert/Hunt 양쪽 경로, 다른 Incident 후보, 경로 없음·미완료·과거·알 수 없는 상태를 담고 관계도·권한·긴 경로 테스트를 추가했다.

## 계획과 달라진 점

- 계획에서 정한 고정층 배치의 Incident 노드를 첫 Ticket 위에 놓았다. 좁은 패널의 처음 보이는 영역에서 Incident와 소속 Ticket을 바로 읽을 수 있게 하기 위해서다.

## 다음 사람이 알아야 할 것

- `ticket_graphs[].ticket_id`는 출발 Ticket이고 `GraphPath.ticket_id`는 상대 Ticket이다. 경로의 마지막 `belongs_to`는 Incident 소속선과 중복되므로 별도 연결 근거로 세지 않는다.
- 첫 Ticket의 자기 분류 기록에 경로가 없어도, 후속 Ticket의 저장 경로가 그 Ticket에 도달할 수 있다.
- 그래프는 기존 API의 후보 탐색 경로를 표시한다. 에이전트가 최종 선택에 사용한 특정 경로를 뜻하지 않는다. 다른 Incident 후보 경로는 Incident ID로 걸러야 한다.
- 그래프 화면은 새 프론트엔드 의존성 없이 HTML 노드와 SVG 선을 사용한다. 노드의 `(kind, id)`와 선의 시작·끝·종류를 키로 중복을 제거한다. 길어진 그래프는 패널 안에서 가로로 스크롤한다.
- Windows에서 `pnpm --dir frontend lint`와 `pnpm --dir frontend contracts:check`가 실패하면 줄끝 문자 때문이지 형식이 어긋난 것이 아니다. git이 체크아웃할 때 CRLF로 바꿔 둔 파일을 Prettier(`endOfLine: "lf"` 기본값)와 생성 스크립트의 문자열 비교가 차이로 본다. 이 작업이 건드린 5개 파일은 LF라 그대로 통과한다.
  - 줄끝을 빼고 보면 전부 통과한다: `npx prettier --check --end-of-line auto .` → `All matched files use Prettier code style!`.
  - `contracts:check`는 `pnpm --dir frontend contracts`로 생성 파일을 다시 쓰면 통과한다(35개 일치). 내용은 바뀌지 않아 git diff가 비어 있다.
  - CI는 ubuntu-latest에서 LF로 체크아웃하므로 두 검사 모두 영향을 받지 않는다. 레포 차원에서 없애려면 `.gitattributes`에 `* text=auto eol=lf`를 더해야 하는데, 모두가 쓰는 설정이라 이 이슈에서는 건드리지 않았다.
- `config/local.toml`을 두면 `tests/test_api.py::test_default_settings`, `::test_main_runs_uvicorn_on_configured_host_and_port`, `tests/test_auth.py::test_default_auth_settings` 3개가 깨진다. 이 테스트들이 실제 `config/` 디렉터리를 읽는데 `local.toml`이 기본값 위에 덮이기 때문이다. 로컬에서 포트나 origin을 바꿔 띄웠다면 테스트 전에 치운다.
- 전체 Python 테스트는 Windows에서 1884개 통과, 2개 실패다. 이 작업은 Python 코드를 바꾸지 않았고 둘 다 이 이슈와 무관한 Windows 전용 기존 실패다. Linux CI에서는 나지 않는다.
  - `tests/test_migrate.py::test_name_ending_in_newline_is_not_a_migration`: Windows가 줄바꿈으로 끝나는 파일명을 만들지 못해 테스트 준비 단계에서 `OSError: [Errno 22]`가 난다.
  - `tests/test_tools_local_intel.py::test_tools_make_no_network_calls`: Windows의 `asyncio.run`이 ProactorEventLoop 자기 파이프를 만들 때 `socket.socketpair()`가 127.0.0.1로 실제 `connect`를 하고, 테스트가 막아둔 `socket.socket.connect`에 그것이 걸린다. 도구 코드가 네트워크를 쓰는 것이 아니다.

## 확인 방법

- `pnpm --dir frontend test`(85개 통과), `pnpm --dir frontend build`, `pnpm --dir frontend contracts:check`(35개 일치), 수정한 파일의 ESLint·Prettier, 줄끝을 뺀 전체 Prettier, `uv run ruff format --check .`(392개 파일), `uv run ruff check .`, `uv run pytest`를 실행했다.
- 수작업 fixture를 임시 Vite 미리보기에 띄워 375·768·1440px 화면과 360·650·1100px 폭에서 확인했다. 12개 노드, 현재 경로 선 6개, 소속선 7개가 보였고 노드 겹침·본문 가로 넘침·콘솔 오류는 없었다. 360px 폭에서 관계도에 초점을 둔 뒤 방향키로 가로 스크롤되는 것을 확인했다.
