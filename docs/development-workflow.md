# Development Harness 구조 및 개발 가이드

프로젝트 개발 과정에 Harness를 활용하기 위해 해당 가이드를 꼭 숙지 후 개발을 진행해주세요.

프로젝트 Harness 구조도는 다음과 같습니다.
```bash
├── AGENTS.md #Harness의 최상위 규칙으로 AI가 개발 전에 해당 문서를 무조건 읽고 시작
├── CLAUDE.md #Claude Code가 공통 개발 규칙인 AGENTS.md를 따르도록 연결하는 파일
├── .agents/ #Codex skill
│   └── skills/
│       ├── soc-test-fix/SKILL.md
│       ├── soc-plan/SKILL.md
│       ├── soc-implement/SKILL.md
│       └── soc-decision/SKILL.md
├── .claude/ #Claude code skill (Codex 스킬과 동일)
│   └── skills/
│       ├── soc-test-fix/SKILL.md
│       ├── soc-plan/SKILL.md
│       ├── soc-implement/SKILL.md
│       └── soc-decision/SKILL.md
├── prompts/ #개발 Workflow 프롬프트
│   ├── 01-plan.md #구현 전에 무엇을 할지 조사하고 계획하는 단계 (이슈 기준) -> 사람이 승인 후 다음 단계로
│   ├── 02-implement.md #승인된 Plan을 실제 코드로 옮기는 단계 -> Plan 외에 기능을 갑자기 만들거나 하지 않음
│   ├── 03-test-and-fix.md #구현 결과를 실제로 검증하고 필요한 수정을 하는 단계
│   └── decision-review.md #아직 확정되지 않은 기술 결정을 검토할 때 사용하는 별도 Workflow
├── docs/ #프로젝트의 기준 문서
│   ├── product-spec.md #무엇을 만들 것인가 (개발할 도구의 목적이 흐려지지 않도록)
│   ├── architecture.md #시스템을 어떤 구조로 만들 것인가 (시스템 전체 아키텍처)
│   ├── data-contracts.md #컴포넌트 사이 데이터 형식 (프로젝트에서 공통으로 사용해야 할 구조를 정의)
│   ├── extensibility.md #확장 가능하게 만드는 원칙 (SIEM, LLM 모델 등 추후 기업에 맞게 커스텀, 확장 가능한 개발을 위함)
│   ├── decisions.md #사람이 확정한 기술 결정 (각 개발 과정에 필요한 외부 도구나 방식을 확정짓고, 개발에 이용)
│   ├── security-policy.md #개발/데이터/비밀 관련 보안 기준 (개발 과정에서도 보안 중시를 위함)
│   ├── llm-policy.md #LLM 호출 및 출력 검증 기준 (LLM을 호출하는 코드를 짤 때만 읽음)
│   ├── frontend.md #웹 화면 목록, 표시 규칙, 검토 동작, 화면 명령 (화면 작업할 때 읽음)
│   ├── api-contracts.md #화면이 부르는 API 목록과 응답 모양 (화면, API 작업할 때 읽음)
│   └── development-workflow.md #Development Harness의 구조, 역할, 개발 Flow를 설명하는 사람용 가이드
├── CONTRIBUTING.md #추후 외부 인원이 기여할 때 확인할 문서
├── src/soc/ #백엔드 코드가 위치할 예정 (화면용 API는 src/soc/api/)
├── frontend/ #웹 화면 코드가 위치할 예정 (F0에서 만듦)
├── tests/ #테스트 관련 문서
│   ├── checklist.md #무엇을 구현해야 완료라고 볼 것인가 확인하는 체크리스트
│   ├── fixtures/ #테스트용 입력 데이터
│   └── test_smoke.py #환경이 제대로 설치됐는지 확인하는 기본 테스트
└── README.md
```

> ## Skill과 Prompt의 관계
> `.agents/skills/`와 `.claude/skills/`는 각 개발 도구에서 특정 개발 단계를 시작하기 위한 진입점입니다.
>
> 실제 개발 절차의 원본은 `prompts/`에 위치하며,
> Skill은 해당 Prompt를 참조하여 실행하는 얇은 진입점으로 유지합니다.
>
> 따라서 개발 절차를 변경할 때는 가능한 한 `prompts/`를 수정하고,
> Codex와 Claude의 Skill에 동일한 절차를 중복 작성하지 않습니다.

## 개발 Flow

### Step 1. 사람이 Issue 생성

이슈 템플릿에 맞게 구체적이고, 정확한 정보만으로 이슈 생성해야 합니다.

### Step 2. Plan 요청

Claude code와 Codex를 통해 아래와 같이 Plan skill을 호출할 수 있습니다.

```text
#Claude Code
/soc-plan (이슈 번호)

#Codex
$soc-plan (이슈 번호)
```

ex)
```text
#Claude Code
/soc-plan 12

#Codex
$soc-plan 12
```


위와 같이 요청하면 각 AI가 skill을 호출하여 prompts/01-plan.md를 읽고, 여러 하네스 문서를 확인 후 Plan 결과를 출력합니다.

해당 단계에서는 코드 수정은 이루어지지 않고, 각 문서를 기반으로 이슈를 어떻게 구현할지 계획만 합니다.

### Step 3. 사람이 Plan 승인

AI가 계획한 내용을 확인하고, 그대로 진행할지 어떠한 변경이 필요한지 명령을 추가적으로 내립니다.
-> 승인하지 않는 경우에는 어떤 부분을 어떻게 고쳐야할지 AI에게 추가 프롬프팅을 해야합니다.

### Step 4. Implement

사람이 확인 후 승인을 위해 다음 명령을 입력하면 구현 skill이 호출됩니다. (prompts/02-implement.md)

```text
#Claude Code
/soc-implement (이슈 번호)

#Codex
$soc-implement (이슈 번호)
```

ex)
```text
#Claude Code
/soc-implement 12

#Codex
$soc-implement 12
```

해당 Skill이 호출되면 AI는 review 기준으로 브랜치를 만들고, 팀원 본인의 git 계정으로 로컬 커밋을 합니다. 이후 승인된 계획 내에서만 개발을 진행합니다.

### Step 5. Test & Fix

구현이 완료되고, 테스트하고 수정을 위해 아래 명령을 전달하면, Test skill이 호출됩니다. (prompts/03-test-and-fix.md)

```text
#Claude Code
/soc-test-fix (이슈 번호)

#Codex
$soc-test-fix (이슈 번호)
```

ex)
```text
#Claude Code
/soc-test-fix 12

#Codex
$soc-test-fix 12
```

해당 Skill이 호출되면 테스트, 오류 분석, 코드 수정 등을 진행하여 해결합니다.

### Step 6. PR 초안 생성

계획부터 테스트까지 모든 과정이 끝나고 Step 5가 종료되면 AI가 PR에 포함되어야 할 메시지 초안을 생성해줍니다.

해당 초안을 기반으로 사람이 직접 PR을 진행합니다.

### Step 7. 사람이 Push / PR / Review / Merge

최종적으로 사람이 Github에 Push하고 PR을 올립니다.

이후 팀원의 리뷰가 모두 진행되면 review 브랜치로 Merge 합니다.

main 브랜치에 Merge하기 위해서는 교수님께 미팅 또는 github PR에서 승인을 받은 후 진행합니다.

### 기술 결정이 필요한 경우의 별도 Step

만약, 계획 또는 구현 준비 과정에서 아직 사람이 확정하지 않은 기술 결정이 필요한 경우, `decision-review.md`를 사용하여 선택지, 장단점, 프로젝트 영향 등을 검토합니다.

```text
#Claude Code
/soc-decision (결정이 필요한 항목)

#Codex
$soc-decision (결정이 필요한 항목)
```

ex)
```text
#Claude Code
/soc-decision D-014

#Codex
$soc-decision D-014
```

Agent가 기술 결정을 임의로 확정하지 않고, 최종 결정은 사람이 내린 후 `docs/decisions.md`에 반영합니다.

`docs/decisions.md`에 확정으로 반영되어야 AI가 해당 구조와 도구를 이용할 수 있습니다.

## 브랜치 및 PR 규칙

### 브랜치 규칙

개발 작업은 팀 내부 검토가 완료된 최신 상태를 기준으로 하기 위해 `review` 브랜치에서 분기합니다. 

브랜치 이름은 `<type>/<이슈번호>-<짧은설명>` 형식입니다. 한글 작성 없이 영문으로 작성합니다.
ex) `feat/12-ocsf`

type에는 `feat`(새 기능), `fix`(버그), `docs`(문서만), `test`(테스트·샘플만), `refactor`(동작 그대로 구조만), `chore`(설정·CI·의존성·하네스)만 사용될 수 있습니다.

### 커밋 메시지 및 PR 규칙

커밋 메시지와 PR 제목은 `<type>(<scope>): <설명> (#이슈번호)`으로 사용합니다.
ex) 
```text
새 기능 : feat(box4): add OCSF normalization (#12)
버그 : fix(core): handle empty alert input (#21)
문서 작업 : docs(harness): update development workflow (#30)
```

scope에는 박스 작업이면 `box<번호>`, 웹 화면이면 `frontend`, 화면용 API면 `api`, 아니면 `core`, `contracts`, `llm`, `config`, `docs`, `ci`, `harness` 중 하나를 사용합니다.

summary는 영어로 짧게 동사 원형으로 시작하고(`add`, `fix`, `update`) 첫 글자는 소문자, 마침표 없이 작성합니다.

개발 완료 후에는 작업 브랜치에서 `review` 브랜치로 PR을 생성합니다.

본인을 제외한 팀원 3명의 승인을 받은 경우 `review`에 Merge할 수 있습니다.

`review`에 반영된 변경사항은 교수님의 미팅 또는 GitHub PR 승인을 받은 후 `main` 브랜치로 최종 Merge합니다.