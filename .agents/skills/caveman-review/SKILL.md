---
name: caveman-review
description: >
  Compressed code review in Korean - one line per finding with location, problem and fix.
  Use ONLY when explicitly invoked (/caveman-review in Claude Code, $caveman-review in Codex).
  Do not use for general review requests such as "review this PR", "코드 리뷰해줘", or /review.
disable-model-invocation: true
---

Write code review comments terse and actionable, **in Korean**. One line per finding. Location, problem, fix. No throat-clearing.

## Language

- Write every comment body in Korean, using terse noun-ending style (명사형·개조식 종결: "~없음", "~필요", "~할 것").
- Keep code identifiers, file paths, line numbers, and severity tags (`bug:`, `risk:`, `nit:`, `q:`) as-is in English.
- Do not translate symbol/function/variable names.

## Rules

**Format:** `L<line>: <problem>. <fix>.` — or `<file>:L<line>: ...` when reviewing multi-file diffs.

**Severity prefix (optional, when mixed):**
- `🔴 bug:` — broken behavior, will cause incident
- `🟡 risk:` — works but fragile (race, missing null check, swallowed error)
- `🔵 nit:` — style, naming, micro-optim. Author can ignore
- `❓ q:` — genuine question, not a suggestion

**Drop:**
- "I noticed that...", "It seems like...", "You might want to consider..."
- Korean equivalents: "~인 것 같아요", "혹시 ~", "~하시는 게 어떨까요?", "~해보시면 좋을 것 같습니다"
- "This is just a suggestion but..." / "사소하지만..." — use `nit:` instead
- "Great work!", "Looks good overall but..." / "전반적으로 좋네요" — say it once at the top, not per comment
- Restating what the line does — the reviewer can read the diff
- Hedging ("perhaps", "maybe", "I think", "아마", "~일 수도") — if unsure use `q:`

**Keep:**
- Exact line numbers
- Exact symbol/function/variable names in backticks
- Concrete fix, not "consider refactoring this" / "리팩터링 고려"
- The *why* if the fix isn't obvious from the problem statement

## Examples

❌ "42번째 줄에서 user 객체가 null인지 확인하지 않고 email 속성에 접근하고 계신 것 같아요. 사용자를 DB에서 못 찾으면 크래시가 날 수도 있을 것 같은데, null 체크를 추가해보시는 게 어떨까요?"

✅ `L42: 🔴 bug: .find() 후 user가 null일 수 있음. .email 접근 전 가드 추가.`

❌ "이 함수가 하는 일이 좀 많아 보여서, 가독성을 위해 작은 함수로 나눠보면 좋을 것 같습니다."

✅ `L88-140: 🔵 nit: 50줄 함수가 4가지 일을 함. validate/normalize/persist로 분리.`

❌ "API가 429를 반환하면 어떻게 되는지 고려해보셨나요? 아마 그 경우도 처리해야 할 것 같아요."

✅ `L23: 🟡 risk: 429 응답 시 재시도 없음. withBackoff(3)로 감쌀 것.`

✅ `normalizer.py:L57: ❓ q: severity 매핑 누락 시 기본값 0이 의도된 것인지?`

## Auto-Clarity

Drop terse mode for: security findings (CVE-class bugs need full explanation + reference), architectural disagreements (need rationale, not just a one-liner), and onboarding contexts where the author is new and needs the "why". In those cases write a normal Korean paragraph, then resume terse for the rest.

## Boundaries

Reviews only — does not write the code fix, does not approve/request-changes, does not run linters. Output the comment(s) ready to paste into the PR. "stop caveman-review", "normal mode", or "일반 모드": revert to verbose review style.
