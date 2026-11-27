---
issue: 403
date: 2026-11-27
owner: Pandyo
supersedes: []
---

# L3 가설 생성에 로그 조회 구간 전달

## 목표

가설 생성 run의 입력에 검증 run과 같은 `window`(`from`, `to`, UTC epoch 밀리초)를 넣고, 지시문이 조회 도구의 `start_ms`·`end_ms`에 그 값을 그대로 쓰게 한다. 모델이 뉴스 시각으로 구간을 어림하다 도구 인자를 추론에만 쓰고 `format_error`로 끝나던 일(2026-11-27, 서버)이 없어진다. 원인이 구간이라는 것은 한 번 본 실패에서 낸 추정이며, 아래 실측으로 확인한다.

## 방법

1. `src/soc/l3/hunt/settings.py`에 `lookback_window(settings, now)`를 둔다. `{"from": to_epoch_ms(now - timedelta(days=lookback_days)), "to": to_epoch_ms(now)}`를 돌려준다.
2. `verify.py`의 `handle`이 이 함수로 `window`를 만든다. 만들어지는 값은 지금과 같다.
3. `hypothesize.py`가 `data`에 `window=lookback_window(settings, now)`를 더한다. `now`는 이미 인자다.
4. `l3_hypothesize.md`에 `window`는 조회할 기간(`from`, `to`, UTC epoch 밀리초)이라는 설명을 더한다. 조회 도구를 부를 때 `from`→`start_ms`, `to`→`end_ms`로 값을 그대로 쓰고 시각을 직접 계산하지 말라고 한 줄로 적는다. `l3_verify.md`는 바꾸지 않는다.
5. `config/default.toml`의 `lookback_days` 주석에 가설 생성 입력의 `window`에도 쓴다는 것을 더한다.

테스트를 먼저 쓴다. 가짜 `run`이 받은 `AgentTask.data["window"]`를 검사한다. 새 도구, 설정 키, 환경변수는 없다.

## 바꿀 곳

- `src/soc/l3/hunt/settings.py`: `lookback_window` 추가
- `src/soc/l3/hunt/verify.py`: `window` 계산을 `lookback_window`로 바꾼다(동작 그대로)
- `src/soc/l3/hunt/hypothesize.py`: 입력에 `window` 추가
- `src/soc/l3/prompts/l3_hypothesize.md`: `window` 설명과 `start_ms`·`end_ms` 대응
- `config/default.toml`: `lookback_days` 주석
- `tests/test_l3_hunt.py`(또는 같은 폴더의 L3 테스트): `lookback_window`, 가설 생성 입력의 `window`
- `docs/notes/403-l3-hypothesize-window.md`: 개발 기록과 실측 절차(개발 단계에서 쓴다)

## 다른 코드와 맞물리는 곳

- 가설 생성 `AgentTask.data`에 키 `window`가 늘어난다. 검증 입력과 같은 모양이다. 이 입력을 읽는 다른 코드는 모델 지시문뿐이다.
- `verify.py`는 내부 계산만 공용 함수로 옮기고 입력 값은 그대로다.
- 그 밖에는 없음.

## 범위 밖

- `l3_verify.md` 수정
- `format_error` 재요청이나 추론만 있는 응답을 코어에서 다르게 다루는 일
- 지난 계획·기록 문서 수정

## 완료 기준

- [ ] 가설 생성 입력에 `window.from`, `window.to`가 들어가고, `to`는 생성 시각, `to - from`은 `lookback_days`일(ms)이다(테스트).
- [ ] `lookback_window`를 단위 테스트하고, `verify.py`의 `window`가 이전과 같다(기존 검증 테스트 통과).
- [ ] `l3_hypothesize.md`가 `window`를 설명하고 `from`→`start_ms`, `to`→`end_ms`로 그대로 쓰게 적는다.
- [ ] `config/default.toml`의 `lookback_days` 주석이 가설 생성에도 쓴다고 적는다.
- [ ] 기존 가설 생성·검증 테스트가 통과한다.
- [ ] 사람이 실제 모델로 `soc.l3 hunt`를 3번 돌리고, 실행별 표를 PR에 적는다. 표 항목은 가설 생성 성공 여부, 조회 인자 `start_ms`·`end_ms`, 추론만 있는 응답 횟수다. 실행 절차, Agent Log 조회, 표 양식은 `docs/notes/403-l3-hypothesize-window.md`에 둔다.
  - 통과: 3번 모두 가설 생성에 `format_error`가 없고, 조회를 호출했다면 `start_ms`·`end_ms`가 `window` 값과 같다.
  - 조회를 한 번도 부르지 않은 실행은 인자 일치를 확인하지 못한 것으로 표에 적는다.
  - `window`를 정확히 썼는데도 추론만 있는 응답으로 실패하면 구간만의 문제가 아니라고 기록하고 별도 이슈 초안을 만든다.
  - `window`를 쓰지 않았으면 지시문을 고친다.

## 토론으로 정한 것

이슈 본문과 달라진 점이다.

- 구간 계산을 `settings.py`의 공용 함수로 뽑는다(이슈는 `verify.py`의 전달 방식을 따르라고만 했다). 두 곳의 값이 갈라지지 않게 하고, `verify.py`의 동작은 바꾸지 않는다.
- 조회 도구 인자가 `start_ms`·`end_ms`라서(`soc/tools/siem.py`, `soc/tools/internal.py`) 지시문에 `from`→`start_ms`, `to`→`end_ms` 대응을 적는다. `l3_verify.md`는 성공한 입력이라 측정 없이 바꾸지 않는다. 필요하면 별도 이슈로 올린다.
- 완료 기준 4는 사람이 실행하고, 통과선과 실패했을 때의 처리를 위처럼 정했다. 실행 절차·조회·표는 개발 쪽에서 준비한다.
- 문서는 `config/default.toml` 주석만 고친다. `docs/plans/223-threat-hunt.md`의 "검증 run의 조회 기간" 같은 지난 계획은 규칙 8대로 두고, 이 계획이 `lookback_days`의 쓰임을 가설 생성까지 넓힌다.

## 바뀐 점
