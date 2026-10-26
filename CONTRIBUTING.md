# 기여 안내

0-Ticket SOC에 기여하는 방법입니다. 이 레포는 사람과 AI 코딩 도구(Claude Code, Codex 등)가 함께 개발합니다. AI 도구가 따르는 지침은 [AGENTS.md](AGENTS.md)에 있고, 이 문서는 사람 기여자를 위한 안내입니다.

## 개발 환경

백엔드는 Python 3.12 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 웹 화면(`frontend/`)은 Node가 필요하고, 버전과 명령은 [docs/frontend.md](docs/frontend.md) "명령"에 있습니다.

```bash
uv sync                 # 의존성 설치
cp .env.example .env    # 필요한 값만 채움
uv run pytest           # 테스트 (실제 LLM 호출 테스트는 기본 제외)
uvx ruff check .        # 린트
uvx ruff format .       # 포맷
```

실제 LLM을 부르는 테스트는 `uv run pytest -m llm`으로 따로 실행합니다. 키가 필요합니다.

DB가 필요한 테스트(`db` 마커)는 기본 실행에서 빠집니다. 개발용 PostgreSQL을 띄우고 따로 실행합니다. CI는 PostgreSQL 서비스 컨테이너로 같은 테스트를 돌립니다.

```bash
docker compose up -d                  # 개발용 PostgreSQL·Qdrant (.env의 POSTGRES_*, DATABASE_URL 필요)
uv run python -m soc.db.migrate       # 마이그레이션 적용
uv run pytest -m db                   # DB 테스트
```

마이그레이션은 `src/soc/db/migrations/`에 `NNNN_<이름>.sql`로 추가합니다. 이미 적용된 파일은 고치지 않고 새 번호의 파일을 만듭니다.

## 작업 흐름

```
작업 브랜치 ──작업 PR (squash)──▶ review ──릴리스 PR (merge commit)──▶ main ──▶ 태그 vX.Y.Z
             팀원 3명 승인 + CI              교수님 승인 + CI
```

1. **이슈 만들기**: "작업 이슈" 템플릿으로 무엇을, 왜, 완료 기준을 적습니다. 여러 박스의 계약 변경은 계약 이슈와 박스별 구현 이슈로 나눕니다. 묶는 기준은 아래 "여러 이슈가 한 계약 변경을 이루는 경우"를 따릅니다.
2. **브랜치**: 최신 `review`에서 만듭니다. 이름은 아래 "브랜치 이름"을 따릅니다.
3. **구현**: 아래 "AI 도구와 함께 일하기"의 세 단계를 따릅니다. 사람이 직접 짜도 같은 순서를 권장합니다.
4. **작업 PR**: `review`로 PR을 엽니다. 팀 리뷰를 거쳐 `review`에 합칩니다.
5. **릴리스 PR**: 교수님 승인을 받은 `review`를 `main`으로 합치고 태그를 붙입니다.

`main`과 `review`에는 직접 커밋하거나 push하지 않습니다. 둘 다 PR로만 바뀝니다.

이 저장소는 GitHub의 브랜치 보호 규칙(유료 기능)을 쓰지 않습니다. 그래서 아래의 승인 수, 머지 방식, 직접 push 금지는 GitHub이 막아 주지 않고 **팀 규칙으로 지킵니다**. 머지 버튼을 누르기 전에 조건을 직접 확인합니다. CI는 무료로 돌아가므로 PR마다 결과가 표시됩니다.

## 브랜치 이름

`<type>/<이슈번호>-<짧은설명>` 형식입니다. 짧은설명은 영어 소문자와 하이픈으로 씁니다.

```bash
git fetch origin
git switch -c feat/12-ocsf-alias origin/review
```

| type | 쓰는 때 |
|---|---|
| `feat` | 새 기능. 박스 구현 등 |
| `fix` | 버그 수정 |
| `docs` | 문서만 바꿈 |
| `test` | 테스트나 샘플만 추가하거나 고침 |
| `refactor` | 동작은 그대로 두고 구조만 바꿈 |
| `chore` | 설정, CI, 의존성, 하네스 |

## 커밋 메시지와 PR 제목

`<type>(<scope>): <summary> (#이슈번호)` 형식입니다.

- **type**: 위 표와 같습니다. 브랜치의 type과 맞춥니다.
- **scope**: 박스 작업이면 `box<번호>`(예: `box4`). 웹 화면이면 `frontend`, 화면용 API면 `api`. 그 밖에는 영역 이름: `core`, `contracts`, `llm`, `config`, `docs`, `ci`, `harness`
- **summary**: 영어로 짧게 씁니다. 동사 원형으로 시작하고(`add`, `fix`, `update`), 첫 글자는 소문자, 끝에 마침표를 찍지 않습니다. 50자 안팎을 권장합니다.

```
feat(box4): add OCSF alias table loader (#12)
fix(box6): fix dedup window boundary check (#21)
docs(contracts): clarify C3 extensions field (#15)
chore(ci): run CI on pushes to review (#3)
```

작업 PR은 squash로 합쳐지므로 **PR 제목이 `review`에 남는 커밋 메시지**가 됩니다. PR 제목을 반드시 이 형식으로 씁니다. GitHub이 끝에 PR 번호를 붙여 `... (#12) (#34)`처럼 되는데, 이슈 번호와 PR 번호가 함께 남는 것이므로 그대로 둡니다. 브랜치 안의 커밋도 같은 형식을 권장합니다.

## 여러 이슈가 한 계약 변경을 이루는 경우

여러 박스가 같은 계약을 쓴다는 사실만으로 이슈를 한 PR에 묶지 않습니다. 계약 변경을 완료하는 데 필수인 생성·저장·재조회·소비 호환 작업을 나눠 병합하면 승인된 계약의 완료 기준을 만족하지 못하거나 중간 상태의 호환성을 보장할 수 없는 경우, 계약 이슈와 박스별 이슈를 하나의 작업 그룹으로 묶습니다. 각 이슈가 안전하게 순차 병합될 수 있고 독립된 완료 기준을 갖는 후속 작업은 별도 PR로 둡니다.

계약 이슈는 공유 필드의 의미와 Schema·생성 코드 범위를 맡고, 박스 이슈는 해당 박스의 동작·호환 코드와 테스트를 맡습니다. 각 이슈의 완료 기준은 이 책임에 맞게 씁니다.

그룹 담당자 한 명이 그룹의 모든 이슈를 하나의 작업 브랜치에서 구현·검증하고 PR 하나를 준비합니다. 이슈는 박스별 범위와 완료 기준을 추적하는 단위로 유지합니다.

### 그룹 이슈 연결

사람이 각 그룹 이슈 본문의 `함께 반영할 이슈` 항목에 같은 조정 이슈 번호를 적고, 자기 자신을 제외한 모든 그룹 이슈를 각각 `Refs #<번호>`로 연결합니다. 조정 이슈는 그룹의 기존 이슈 중에서 사람이 지정합니다. 각 이슈의 번호와 이 항목의 `Refs`를 합친 목록이 모두 같고, 조정 이슈가 그 목록에 포함돼야 합니다. 다른 항목의 참고 링크나 `Refs`만으로 그룹에 포함하지 않습니다. 단일 이슈는 이 항목을 `해당 없음`으로 두며, 기존 이슈에 항목이 없더라도 계약 영향 분석에서 그룹이 필요하면 연결 보완을 제안합니다.

예를 들어 #120·#121·#122를 묶고 #120을 조정 이슈로 정했다면, #120에는 다음을 적습니다.

```markdown
## 함께 반영할 이슈

조정 이슈: #120

Refs #121
Refs #122
```

#121에는 같은 조정 이슈와 `Refs #120`, `Refs #122`를, #122에는 같은 조정 이슈와 `Refs #120`, `Refs #121`을 적습니다. `.github/ISSUE_TEMPLATE/task.md`에 이 항목의 작성 안내가 있습니다.

계획은 시작 이슈 하나로 요청할 수 있습니다. AI는 연결된 이슈들을 읽고 그룹 후보와 이슈별 완료 기준을 정리한 뒤 위의 그룹 조건을 확인합니다. 연결은 계획 승인을 대신하지 않습니다. 누락·불일치가 있으면 AI가 이슈별 수정 문구를 출력하고, 사람이 GitHub 본문을 수정한 뒤 AI가 다시 조회합니다. 필요한 이슈가 아직 없으면 사람이 먼저 만듭니다. 연결이 일치하기 전에는 그룹을 확정하거나 구현하지 않습니다. 그룹을 바꿀 때는 추가·제외되는 이슈를 포함해 각 이슈의 연결도 함께 갱신합니다.

### 그룹 계획과 구현

통합 계획에는 다음을 모두 적고 사람이 승인합니다.

- 그룹 이슈 번호와 이슈별 박스·완료 기준
- 계약 변경안의 필드 의미, 타입, nullable·기존 데이터 호환 규칙
- 그룹을 나눠 병합할 수 없는 이유와 같은 PR에 필요한 변경
- 그룹의 기존 이슈 중 사람이 지정한 조정 이슈, 그룹 담당자 한 명, 브랜치 이름, PR 제목과 검증 범위

계약 변경안과 그룹 전체가 명시적으로 승인된 뒤 구현합니다. 구현 시작·재개 전에는 최신 이슈의 그룹 목록과 조정 이슈를 승인 계획과 대조합니다. 그룹 구성, 조정 이슈, 담당자, 계약 의미나 박스 범위가 바뀌면 계획을 갱신하고 다시 승인받습니다. 조정 이슈는 계약 이슈라고 자동으로 정하지 않습니다. 그룹 담당자가 전체 구현·검증과 PR 준비를 맡으며, 같은 그룹의 이슈별 `review` PR은 만들지 않습니다.

그룹 담당자는 최신 `origin/review`에서 조정 이슈 번호로 작업 브랜치를 만듭니다. 구현을 재개할 때는 승인 계획에 적힌 기존 브랜치와 작업 내용을 확인하고 이어서 작업합니다.

```text
<type>/<조정이슈번호>-<short-description>
<type>(<scope>): <summary> (#<조정이슈번호>)
```

커밋과 PR 제목은 기존 형식을 따르며 조정 이슈 번호를 씁니다. 조정 이슈가 계약 변경을 대표하면 PR 제목에는 보통 `contracts` scope를 쓰고, PR 본문에는 그룹의 모든 이슈를 이슈마다 별도 `Refs` 줄로 적습니다. 조정 이슈와 그룹 담당자는 승인된 계획에도 기록합니다.

```markdown
Refs #<조정이슈번호>
Refs #<박스별 이슈 번호>
Refs #<다른 박스별 이슈 번호>
```

구현 순서는 `docs/data-contracts.md`의 절차를 따릅니다: 계약 문서 → `contracts/` Schema → 생성 명령 → 영향받는 박스·화면 코드와 테스트. 각 그룹 이슈의 완료 기준을 확인하고, 영향받는 모든 박스의 계약 fixture·테스트·체크리스트를 검증합니다. 계약을 바꾸면 `uv run python scripts/generate_contracts.py`로 Python·TypeScript 코드를 다시 생성하고 생성 재현성 검사를 통과시킵니다. 기존 저장 데이터 호환이 필요한 경우 migration·backfill 경계도 테스트합니다. 마지막에 `uvx ruff format --check .`, `uvx ruff check .`, `uv run pytest`를 실행하며, 화면이 영향받으면 `frontend/AGENTS.md`의 검사도 실행합니다.

## 작업 PR (작업 브랜치 → review)

| 항목 | 규칙 |
|---|---|
| 대상 브랜치 | `review` |
| 제목 | 위 커밋 형식 |
| 이슈 연결 | 단일 이슈는 `Refs #12`. 그룹 PR은 이슈마다 별도 `Refs #n` 줄을 둡니다. `Closes`는 쓰지 않습니다 (아래 참고) |
| 머지 조건 | CI 통과 + 작성자를 뺀 팀원 3명 승인 (작성자 포함 4명) |
| 승인 뒤 코드를 바꾸면 | 승인한 팀원에게 다시 리뷰를 요청합니다 |
| 머지 방식 | Squash and merge. 머지 버튼 옆 ▼에서 방식을 꼭 확인합니다 |
| 머지하는 사람 | 승인이 모이면 작성자가 머지합니다 |
| 머지 후 | 작업 브랜치를 삭제합니다 |

작성자는 자기 PR을 Approve할 수 없으므로, 다른 팀원 3명이 Approve하면 "작성자 포함 4명 승인"으로 봅니다.

`Closes #12`는 기본 브랜치(`main`)로 가는 PR에서만 이슈를 닫습니다. `review`로 가는 PR에 써도 이슈가 닫히지 않으므로 작업 PR은 `Refs`로 연결만 하고, 이슈는 릴리스 PR에서 닫습니다.

## 릴리스 PR (review → main)

교수님 미팅에서 승인받았을 때, 또는 교수님이 main PR에서 직접 검토할 때 엽니다.

| 항목 | 규칙 |
|---|---|
| 대상 브랜치 | `main` (비교 브랜치: `review`) |
| 제목 | `chore(release): v0.1.0` |
| 본문 | 아래 양식 |
| 머지 조건 | CI 통과 + 교수님 승인 (PR 본문에 승인 기록) |
| 머지 방식 | Create a merge commit. squash하지 않습니다. 머지 버튼 옆 ▼에서 방식을 꼭 확인합니다 |
| 머지 후 | 태그를 붙입니다 |

**squash하지 않는 이유**: squash하면 `main`에 새 커밋이 생겨 `review`와 이력이 갈라지고, 다음 릴리스 PR마다 이미 들어간 변경이 충돌합니다. merge commit은 `review`의 커밋을 그대로 가져가므로 이런 일이 없습니다.

교수님 승인은 PR 본문의 "승인" 줄로 남깁니다. 미팅에서 승인받았으면 날짜를 적고, 교수님이 PR에서 직접 검토하셨으면 그 PR 댓글이나 Approve가 기록이 됩니다. 승인 기록이 없는 릴리스 PR은 머지하지 않습니다.

포함된 커밋은 아래 명령으로 확인합니다. 일반 PR은 커밋 제목에서 이슈를 모으고, 여러 이슈가 한 작업 PR에 묶였으면 그 PR 본문의 모든 `Refs` 이슈도 합칩니다. squash 커밋에는 조정 이슈만 남을 수 있으므로 커밋 제목만으로 릴리스 이슈 목록을 만들지 않습니다.

```bash
git fetch origin
git log --oneline origin/main..origin/review
```

릴리스 PR 본문 양식:

```markdown
## 승인

승인: 2026-10-20 교수님 미팅
<!-- 이 PR에서 바로 검토받으면: "승인: 이 PR에서 검토" -->

## 닫는 이슈

<!-- 작업 PR에서 참조한 그룹 이슈를 포함해 이슈마다 Closes를 따로 씁니다. "Closes #12, #13"은 첫 번째만 닫힙니다. -->
Closes #12
Closes #13

## 변경 요약

- feat(box4): add OCSF alias table loader (#12)
- docs(contracts): clarify C3 extensions field (#13)

## 태그

v0.1.0
```

### 태그

머지 후 `main`에 태그를 붙입니다. 1.0 전까지는 `v0.X.0` 형식으로, 릴리스마다 X를 1씩 올립니다.

```bash
git fetch origin
git tag -a v0.1.0 origin/main -m "v0.1.0: 2026-10-20 교수님 승인"
git push origin v0.1.0
```

GitHub의 Releases 화면에서 같은 이름으로 만들어도 됩니다.

## AI 도구와 함께 일하기

AI에게 세 단계로 맡깁니다. 계획은 사람이 확인한 뒤 구현으로 넘어갑니다.

| 단계 | 공통 (어떤 도구든) | Claude Code | Codex |
|---|---|---|---|
| 계획 | "`prompts/01-plan.md` 대로 이슈 #3 진행해" | `/soc-plan 3` | `$soc-plan 3` |
| 구현 | "`prompts/02-implement.md` 대로 진행해" | `/soc-implement 3` | `$soc-implement 3` |
| 테스트·PR 초안 | "`prompts/03-test-and-fix.md` 대로 진행해" | `/soc-test-fix 3` | `$soc-test-fix 3` |
| 결정 검토 | "`prompts/decision-review.md` 대로 D-007 검토해" | `/soc-decision D-007` | `$soc-decision D-007` |

**GitHub에는 AI가 기여자로 남지 않게 합니다.** AI는 로컬 커밋과 PR 제목·본문 초안까지만 하고, push·PR 생성·머지·릴리스 PR·태그는 사람이 합니다. Claude Code는 `.claude/settings.json`이 이를 강제합니다. Codex 등 다른 도구를 쓸 때는 커밋 메시지에 `Co-Authored-By` 같은 표시가 없는지 확인해 주세요.

## 지켜야 할 것

- **기술 선택**: [docs/decisions.md](docs/decisions.md)에서 "확정"된 도구와 데이터셋만 씁니다. 새로 고를 것이 있으면 이슈로 결정 검토를 요청합니다.
- **데이터 형식**: [docs/data-contracts.md](docs/data-contracts.md)의 필드를 바꾸려면 "바꾸는 절차"를 따릅니다.
- **확장 구조**: 바뀔 수 있는 부분은 인터페이스와 구현체로 나누고, 조직별 값은 설정으로 뺍니다. [docs/extensibility.md](docs/extensibility.md)를 보세요.
- **보안**: 비밀 값, 실제 로그, 데이터셋 원본은 커밋하지 않습니다. [docs/security-policy.md](docs/security-policy.md)를 보세요.
- **테스트 데이터**: `tests/fixtures/`의 샘플은 손으로 만들고, IP는 문서용 대역, 도메인은 `example.com`을 씁니다.

## 플러그인 만들기

레포를 고치지 않고 사내 SIEM, 로그 소스, LLM 제공자 등을 붙이려면 별도 Python 패키지로 플러그인을 만들 수 있습니다.

1. 붙이려는 확장 지점의 인터페이스(`src/soc/<그룹>/<확장 지점>/base.py`)를 구현합니다.
2. 플러그인 패키지의 `pyproject.toml`에 `zero_ticket_soc.<확장 지점>` entry point로 등록합니다.
3. 조직 설정에서 그 이름을 지정합니다.

확장 지점 목록, 설정 예시, 플러그인이 바꿀 수 없는 코어 규칙은 [docs/extensibility.md](docs/extensibility.md)에 있습니다. 여러 조직에 쓸모 있는 플러그인은 이 레포에 기여해 주세요.

## 저장소 구조

```
AGENTS.md          AI 코딩 도구 공통 지침
CONTRIBUTING.md    이 문서
docs/              제품·설계·계약·결정·정책 문서
prompts/           AI 작업 단계 지시
.claude/, .agents/ AI 도구별 설정과 스킬
config/            기본 설정 (조직 설정은 커밋하지 않음)
src/soc/           백엔드 코드
frontend/          웹 화면
tests/             테스트, 체크리스트, 샘플 데이터
.github/           이슈·PR 템플릿, CI
```
