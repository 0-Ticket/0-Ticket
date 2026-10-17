# 웹 화면 작업 지침

`frontend/`와 화면용 API(`src/soc/api/`) 작업에 루트 `AGENTS.md`에 더해 적용한다.

## 먼저 읽을 문서

1. `docs/frontend.md`: 그 화면(F 번호)의 경로, 쓰는 계약, 표시 규칙, 검토 동작
2. `docs/api-contracts.md`: 그 화면이 부르는 API와 응답 모양
3. `docs/security-policy.md` 7항: 화면 보안 규칙

## 규칙

- 작업 단위는 `docs/frontend.md`의 화면 하나(F0 ~ F6)다.
- 계약 타입은 `frontend/src/contracts/`(생성 코드)에서만 가져오고, API 호출은 `frontend/src/api/`에만 둔다.
- 화면은 mock(MSW)으로 먼저 만든다. mock은 `docs/api-contracts.md`의 경로와 응답 모양을 그대로 따르고, 화면 코드는 mock인지 모른다.
- 로그 원문, LLM 출력, `extensions` 값은 텍스트로만 표시한다. HTML·마크다운 렌더링과 링크 변환을 하지 않는다.
- 등록형 값 목록을 화면 코드에 고정하지 않는다. 받은 값을 그대로 보여 준다.
- 판정·분기·묶음을 화면에서 계산하지 않는다. LLM, SIEM, DB를 직접 부르지 않는다.
- 대응을 실행하는 버튼이나 API를 만들지 않는다. 쓰기 동작은 검토 입력과 Case 작업 수정뿐이다.
- 사람은 L1 결과를 읽기만 하고(27), 승인은 L2 승인·확정(21)에서만 한다. L1 판정을 바꾸는 화면 동작을 새로 만들지 않는다.
- F1 검토 대기함(→ 읽기 전용 L1 결과 조회로 변경 예정), F2 판정 뒤집기(제거 예정), F3 Correlation 출처 표시, F5 룰 승인은 v1 흐름 기준이다. v2에 맞추는 일은 별도 이슈로 하고, 그 이슈 없이 바꾸지 않는다.
- 새 npm 패키지는 결정 대장에 있는 것만 쓰고, 그 밖의 것은 PR "이유"에 적는다.

## 명령

`frontend/`에서 실행한다. Node와 pnpm 버전은 `.nvmrc`와 `package.json`을 따른다.

```bash
pnpm install --frozen-lockfile
pnpm dev            # 개발 서버 (mock)
pnpm typecheck
pnpm lint
pnpm format:check   # 고치지 않고 검사만
pnpm test
pnpm build
```

## 완료 기준 (화면 작업)

루트 `AGENTS.md`의 완료 기준에 더해 `docs/frontend.md` "완료 기준 (화면 작업)"을 만족한다. 위 명령의 타입 검사부터 빌드까지 모두 통과해야 한다.
