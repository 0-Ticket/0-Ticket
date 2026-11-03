# 기여 안내

0-Ticket SOC는 사람과 AI 코딩 도구(Claude Code, Codex)가 함께 개발합니다. AI가 따르는 지침은 [AGENTS.md](AGENTS.md)에 있고, 이 문서는 사람을 위한 안내입니다.

## 개발 환경

Python 3.13과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync                 # 의존성 설치
cp .env.example .env    # 필요한 값만 채움
uv run pytest           # 테스트 (실제 LLM·DB·Qdrant 테스트는 기본 제외)
uv run ruff check .     # 린트
uv run ruff format .    # 포맷
docker compose up -d    # 개발용 PostgreSQL·Qdrant (.env의 POSTGRES_* 필요)
```

실제 LLM·DB·Qdrant가 필요한 테스트는 `uv run pytest -m llm`, `-m db`, `-m qdrant`로 따로 실행합니다.

## 문서

| 문서 | 내용 | 바꿀 때 |
|---|---|---|
| [docs/architecture.md](docs/architecture.md) | 무엇을 만드는지, 원칙, 큰 흐름 | 팀 논의 |
| [docs/decisions.md](docs/decisions.md) | 쓰는 도구와 방식, 아직 정하지 않은 안건 | 결정할 때 |
| [docs/security.md](docs/security.md) | 비밀, 데이터, 화면 표시 규칙 | 팀 논의 |
| [docs/plans/](docs/plans/) | 이슈마다 확정한 계획 | 이슈마다 하나씩 쌓임 |
| [docs/notes/](docs/notes/) | 이슈마다 개발하며 알게 된 것 | 이슈마다 하나씩 쌓임 |

세부 설계는 미리 문서로 쓰지 않습니다. 이슈에서 계획하고, 확정한 계획과 개발 기록을 쌓아 다음 작업이 참고합니다.

## 기점

2026-11-03, PR #191부터 새 하네스로 개발합니다. 그 이전의 브랜치·이슈·PR과 거기 적힌 결정 번호는 참고하지 않습니다. 새 이슈에서 예전 이슈를 꼭 참고해야 하면, 필요한 내용을 새 이슈에 직접 옮겨 적습니다.

## 작업 흐름

```
사람: 계획을 담아 이슈 작성
  │
  ▼
/soc-plan 12   AI가 충돌·오류·빈칸을 질문 ⇄ 사람이 답하고 토론 (반복)
  │            사람이 "확정" → docs/plans/12-*.md 커밋 + 이슈 댓글 초안
  ▼
사람: 댓글 초안을 이슈에 붙임
  │
  ▼
/soc-dev 12    확정 계획대로 샘플 → 테스트 → 코드, 기록을 쓰며 개발
  │
  ▼
/soc-done 12   검사 통과 → docs/notes/12-*.md 마무리 → PR 초안
  │
  ▼
사람: push → PR → 리뷰 → 머지
```

| 단계 | Claude Code | Codex | 공통 (어떤 도구든) |
|---|---|---|---|
| 계획 | `/soc-plan 12` | `$soc-plan 12` | "`prompts/plan.md` 대로 이슈 #12 검토해" |
| 개발 | `/soc-dev 12` | `$soc-dev 12` | "`prompts/dev.md` 대로 진행해" |
| 마무리 | `/soc-done 12` | `$soc-done 12` | "`prompts/done.md` 대로 마무리해" |

- 이슈는 "작업 이슈" 템플릿(무엇을 / 왜 / 어떻게 / 완료 기준)으로 씁니다. 아직 못 정한 것은 "어떻게"에 "정하지 못함"으로 적어 두면 계획 단계에서 함께 정합니다.
- 계획 단계의 토론은 대화로 하고, 레포와 이슈에는 확정 결과와 "왜 그렇게 정했는지"만 남깁니다.
- 개발 중 계획을 바꿔야 하면 AI가 멈추고 묻습니다. 정한 내용은 계획 파일의 "바뀐 점"에 남습니다.
- 절차를 바꾸고 싶으면 `prompts/`의 파일만 고칩니다. 스킬은 그 파일을 부르는 입구입니다.

### 여러 이슈를 한 PR로 묶을 때

나눠 머지하면 중간 상태가 깨지는 경우에만 묶습니다. 각 이슈의 "함께 반영할 이슈"에 같은 조정 이슈 번호를 적고, 자기 자신을 뺀 나머지를 `Refs #<번호>`로 한 줄씩 적습니다. 브랜치, 계획·기록 파일, 커밋, PR 제목에는 조정 이슈 번호를 씁니다.

## 정할 것이 생겼을 때

도구나 방식처럼 팀이 정해야 하는 것은 이슈의 "어떻게"에 적습니다. 정해지면 [docs/decisions.md](docs/decisions.md)의 해당 행을 "확정"으로 옮기고 "기록"에 한 줄을 남깁니다.

## 브랜치 이름

`<type>/<이슈번호>-<짧은설명>` 형식입니다. 짧은설명은 영어 소문자와 하이픈으로 쓰고, 계획·기록 파일 이름과 맞춥니다.

| type | 쓰는 때 |
|---|---|
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서만 바꿈 |
| `test` | 테스트나 샘플만 추가하거나 고침 |
| `refactor` | 동작은 그대로 두고 구조만 바꿈 |
| `chore` | 설정, CI, 의존성, 하네스 |

## 커밋 메시지와 PR 제목

`<type>(<scope>): <summary> (#이슈번호)` 형식입니다.

- **scope**: 주로 바꾼 폴더 이름. 백엔드는 `src/soc/` 바로 아래 폴더 이름, 그 밖에는 `frontend`, `docs`, `plans`(계획 파일), `notes`(기록 파일), `ci`, `harness`
- **summary**: 영어로 짧게. 동사 원형으로 시작하고, 첫 글자는 소문자, 끝에 마침표를 찍지 않습니다.

```
feat(l1): add alert triage agent (#12)
docs(plans): add plan for alert triage (#12)
```

PR은 squash로 합쳐지므로 **PR 제목이 `main`에 남는 커밋 메시지**가 됩니다.

## PR (작업 브랜치 → main)

| 항목 | 규칙 |
|---|---|
| 대상 브랜치 | `main` |
| 제목 | 위 커밋 형식 |
| 본문 | PR 템플릿. 계획·기록 파일 경로를 적습니다 |
| 이슈 연결 | 이슈마다 `Closes #12`를 한 줄씩. `Closes #12, #13`은 첫 번째만 닫습니다 |
| 머지 조건 | CI 통과 + 작성자를 뺀 팀원 3명 승인 (작성자 포함 4명) |
| 승인 뒤 코드를 바꾸면 | 승인한 팀원에게 다시 리뷰를 요청합니다 |
| 머지 방식 | Squash and merge. 머지 버튼 옆 ▼에서 방식을 꼭 확인합니다 |
| 머지하는 사람 | 승인이 모이면 작성자가 머지합니다 |
| 머지 후 | 작업 브랜치를 삭제합니다 |

이 저장소는 GitHub 브랜치 보호 규칙을 쓰지 않습니다. 승인 수, 머지 방식, 직접 push 금지는 **팀 규칙으로 지킵니다**.

## AI 도구 사용 규칙

- **GitHub에는 AI가 쓰지 않습니다.** AI는 로컬 커밋과 이슈 댓글·PR 초안까지만 하고, 댓글 달기·push·PR 생성·머지는 사람이 합니다. Claude Code는 `.claude/settings.json`이 주요 쓰기 명령을 막지만 모든 명령을 막지는 못하므로, AI가 GitHub에 쓰는 명령을 실행하려 하면 거절합니다.
- 커밋 메시지에 `Co-Authored-By` 같은 AI 표시가 없는지 확인합니다.
- 코드 리뷰를 짧게 받고 싶으면 `/caveman-review`(Codex는 `$caveman-review`)를 씁니다.

## 지켜야 할 것

- 기술 선택은 [docs/decisions.md](docs/decisions.md)에서 "확정"된 것만 씁니다.
- 비밀 값, 실제 로그, 데이터셋 원본은 커밋하지 않습니다. [docs/security.md](docs/security.md)를 보세요.
- `tests/fixtures/`의 샘플은 손으로 만들고, IP는 문서용 대역, 도메인은 `example.com`을 씁니다.

## 저장소 구조

```
AGENTS.md          AI 코딩 도구 공통 지침 (CLAUDE.md가 불러옴)
CONTRIBUTING.md    이 문서
docs/              구조, 결정, 보안 규칙
  plans/           이슈별 확정 계획
  notes/           이슈별 개발 기록
prompts/           AI 단계별 절차 (원본)
.claude/, .agents/ AI 도구별 설정과 스킬
src/soc/           백엔드 코드
tests/             테스트와 샘플 데이터 (fixtures/)
.github/           이슈·PR 템플릿, CI
```
