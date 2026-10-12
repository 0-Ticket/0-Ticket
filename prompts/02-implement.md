# 2단계: 구현

사람이 승인한 계획대로 구현한다. 계획에 없는 일은 하지 않는다.

## 입력

- 이슈 번호와 승인된 계획. 승인된 계획이 없으면 1단계(`prompts/01-plan.md`)부터 한다.

## 절차

1. `git fetch origin` 후 `origin/review`에서 브랜치를 만든다. 이름은 `<type>/<이슈번호>-<짧은설명>`이다(예: `git switch -c feat/12-ocsf-alias origin/review`). type은 `AGENTS.md` "작업 흐름"을 따른다. fetch가 안 되면 멈추고 알린다.
2. 계약 변경이 승인됐다면 `docs/data-contracts.md`와 `src/soc/contracts/`부터 고친다.
3. 샘플을 먼저 만든다. `tests/fixtures/`에 손으로 만든 작은 데이터를 둔다. IP는 문서용 대역, 도메인은 `example.com`을 쓴다.
4. 테스트를 먼저 쓰고, 지금은 실패하는지 확인한다.
5. 테스트가 통과하도록 구현한다. 코드 위치는 `docs/architecture.md`의 "박스 그룹과 코드 위치" 표를 따른다.
6. 의미 있는 단위로 나눠 로컬에 커밋한다. 커밋 메시지 첫 줄은 `<type>(<scope>): <summary> (#이슈번호)`이다. 예: `feat(box4): add OCSF alias table loader (#12)`, `test(box4): add alias table fixtures (#12)`

## 지킬 것

- `docs/data-contracts.md`의 필드명, 타입, 필수 여부를 그대로 쓴다.
- 키, 토큰, 비밀번호는 하드코딩하지 않고 환경변수로 읽는다. 새 환경변수가 생기면 `.env.example`에 이름만 추가한다.
- LLM을 부르는 코드는 `docs/llm-policy.md`를 따른다. 테스트는 가짜 응답으로 한다.
- 확장 지점은 `docs/extensibility.md`를 따른다. 인터페이스와 구현체를 나누고, 코어에서 구현체 이름으로 분기하지 않으며, 조직별 값은 설정으로 뺀다. 가짜 구현체로 교체하는 테스트를 함께 만든다.
- "확정"되지 않은 결정 항목의 도구나 데이터셋을 쓰지 않는다.
- 계획과 달라져야 하면 멈추고, 무엇이 왜 달라지는지 먼저 말한다.
- 커밋 메시지에 AI 표시를 넣지 않고, push하지 않는다.

## 출력

- 만든 브랜치 이름
- 변경한 파일과 각각의 이유
- 새로 넣은 라이브러리와 이유 (없으면 "없음")
- 계획과 달라진 점 (없으면 "없음")