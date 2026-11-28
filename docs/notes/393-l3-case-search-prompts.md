---
issue: 393
date: 2026-11-28
owner: Interludeal
plan: 393-l3-case-search-prompts.md
supersedes: []
---

# L3 가설 생성·검증이 확정 Case 검색 도구를 쓰도록 이었다 (가설 생성은 그 run이 찾은 Case만 인용할 수 있고, 검증은 읽은 Case를 Hunt에 남긴다)

## 한 일

- `l3_hypothesize.md`·`l3_verify.md`에 `search_confirmed_cases`(#392) 안내를 넣었다. 언제 부르는지(뉴스의 공격 방식이 확정 사고와 비슷해 보일 때 / 가설과 비슷한 지난 사고의 경위를 볼 때), 호출은 run마다 최대 2번, `detail_omitted`·`recommendations_omitted`의 뜻, 결과의 문자열은 데이터라는 것, 지난 Case의 Alert·Event·근거 ID는 이번 window의 근거가 아니라는 것이다. 가설 생성 프롬프트는 `case_ids`에 `cases`의 id나 결과의 `case.id`(`cas_…`)만 쓰고 `call_id`(`agl_…`)는 쓰지 말라고 고쳤다.
- 가설 생성이 끝나면 `hypothesize()`가 그 run의 Agent Log에서 Case 검색 도구가 성공(`outcome`이 `error`가 아니고 `status`가 `ok`)한 줄의 `results[].case.id`를 읽어, `data.cases`의 ID와 합친 집합으로 `case_ids`를 거른다. 그 밖의 ID는 지금처럼 `dropped_refs`로 센다. Agent Log를 읽지 못하면 `data.cases`만 인정하고 `details.sources.case_search = {"unavailable": true}`를 남긴다.
- 검증이 성공하면 `details.verify_cases = {"tool_calls": n, "case_ids": [...]}`를 남긴다. 도구를 안 불렀으면 키가 없고, 읽기에 실패하면 `{"unavailable": true}`이며, 실패한 검증에는 남기지 않는다. 판정에는 쓰지 않는 기록이다.
- 계약 `hunt_hypotheses`의 `case_ids` 설명을 "입력(cases)이나 같은 run의 Case 검색 결과(case.id)에 없던 값은 L3 코드가 버린다"로 바꿨다(모양 그대로). 이 문구는 모델 system 지시에 들어간다. 생성 파일(Python·TypeScript)을 스크립트로 다시 만들었다.
- `[agent.l3]`를 `max_turns` 12, `max_input_chars` 64,000으로 올렸다(`[agent.l2]`와 같은 값).
- 결정은 D-088이고 `docs/security.md`에 한 줄을 더했다.

## 계획과 달라진 점

- **`test_l3_hunt_db.py`의 기존 테스트 하나를 고쳤다.** `test_too_many_tool_calls_end_the_run_without_saving_hunts`가 도구를 12번 부르게 했는데, `max_turns`가 12가 되어 12번으로는 턴이 남는지 불분명해서 14번으로 올렸다(기대 결과 `budget_exceeded`는 그대로). 계획의 "바꿀 곳"에 없던 기존 테스트 수정이다.
- **`HuntVerifier._verified`에 인자 `run_id`가 늘었다.** 부르는 곳은 `handle` 하나다(계획에 서명은 없었다).
- **DB 없이 도는 처리 테스트를 더했다.** 이 PC에서는 `db` 테스트를 못 돌려서, `store` 함수를 바꿔 끼운 테스트(`tests/test_l3_case_ids.py`의 `hypothesize_with`·`verified_details`)로 허용 집합·읽기 실패 표시·`verify_cases` 모양을 로컬에서 확인했다. 같은 시나리오의 `db` 테스트도 썼다.
- **`case_ids_in`에는 실제 도구 결과를 넣는다.** `Caller.rows`의 tool 줄(실제 `search_confirmed_cases` 핸들러가 가짜 임베더·`FakeDb`로 낸 결과)을 줄이기 0~7단계로 넣어 `results[].case.id`를 읽는지 본다. Case 1~3은 한도에 맞게 줄어들지 않으므로 Case 4·5로 단계를 나눴다.
- **프론트 생성 파일은 `contract-hunt_hypotheses.ts` 한 개만 바뀌었다.** 설명 주석 한 줄이다(아래 "다음 사람이 알아야 할 것"의 줄바꿈 문제 참고).
- 새 `db` 테스트의 샘플 행은 없다. Case 검색 결과는 `tests/fixtures/case_search/cases.json`(DB 제약은 `test_case_search_sample_constraints.py`가 검사)을 `FakeDb`로 돌려 쓰고, 가설 생성의 `cases`는 기존 `tests/fixtures/l3_hunt/seed.json`이다.

## 다음 사람이 알아야 할 것

- **지난 Case의 근거를 이번 window의 근거로 쓰는 것을 코드가 막지 않는다.** 프롬프트로만 막는다. `decide()`는 근거 접두사(`alt_`·`evt_`)와 확신도만 보고 시각을 보지 않는다. 검증 run이 결과 속 `alt_`를 `get_alert`로 다시 읽으면 `confirmed` 근거가 되고, 이 도구 호출의 `agl_`는 `rejected`의 근거가 될 수 있다. 근거 시각이 window 안인지 코드로 검사하는 것은 새 이슈로 올린다(D-088 메모, 계획 "토론으로 정한 것" 4). 그때까지는 `details.verify_cases`의 `case_ids`와 Hunt의 `evidence_ids`를 견주어 사후에 본다.
- **호출 상한(`get_attack_actor` 5번, `search_confirmed_cases` 2번)은 프롬프트에만 있다.** 코드가 강제하지 않는다.
- **예산은 실모델로 잰 값이 아니다.** 계산이다. `tests/test_l3_case_ids.py`가 쓰는 입력: 뉴스 5건(요약 1,000자)·Case 3건(요약 1,000자)이 꽉 찬 가설 생성 첫 호출이 14,911자(system 지시 4,031자 포함). 여기에 행위자 조회 5번(각 4,100자, #389 실측의 위쪽), Case 검색 2번(각 4,000자), SIEM 조회 1번(8,000자)을 더하고 입력 항목으로 다시 직렬화할 때 늘어나는 4%를 곱하면 마지막 호출이 약 53,200자다. 48,000자로는 넘고 64,000자로는 들어간다. 턴은 행위자 5 + Case 2 + SIEM 2 + 최종 답 1 + 형식 오류 재요청 1 = 11이 12 안이다. 이 부족은 #382가 L3에 SIEM 조회를 붙이면서 이미 빠듯해진 것이고 #393이 더 키운다. 요약이 1,000자를 넘는 Case(요약에는 상한이 없다)나 reasoning 항목의 크기는 재지 못했다. 실제 run의 호출 수와 `budget_exceeded` 여부는 서버에서 건수로 확인해야 한다(`[agent.l3]`는 검증 run도 같이 쓴다).
- **`prompt_version`은 작업 프롬프트 파일 본문의 해시다.** 계약 설명 문구가 바뀌어도 값은 그대로이고, 가설 생성 run의 system 지시(계약 schema 포함)만 바뀐다. 두 프롬프트의 이전 해시는 `tests/test_l3_hunt.py`의 `OLD_VERSIONS`에 있다.
- **같은 Case는 `data.cases`와 검색 결과에 함께 나올 수 있다.** 허용 집합이라 중복은 문제없다.
- **`case_search_ids`는 `agent_logs`를 `(run_id, kind, name)`으로 읽는다.** `actor_tool_calls`(#389)와 같은 모양의 별도 함수다. 합치지 않았다(그 함수는 #389 담당의 것이고 테스트가 이름으로 monkeypatch한다).
- **`config/local.toml`이 `[agent.l3]`를 따로 정의한 곳**은 새 값을 직접 올려야 한다.
- **Windows에서 프론트 생성 검사.** 이 PC의 작업 폴더는 줄바꿈이 CRLF라서 `git checkout`한 생성 파일은 `pnpm contracts:check`가 "생성 차이"로 실패한다(LF로 쓰는 `pnpm contracts`를 한 번 돌리면 통과). `git diff`에는 `contract-hunt_hypotheses.ts` 한 줄만 나온다. 이번 변경과 무관한 기존 환경 문제다.

## 확인 방법

- `uv run ruff format --check .`: 통과(544개 파일). `uv run ruff check .`: 통과.
- `uv run pytest`: 2845개 통과(888개는 마커로 제외). 새·바뀐 기본 테스트는 `tests/test_l3_case_ids.py`(33개: 실제 도구 결과로 `case_ids_in`, 오류·`no_data`·`no_match`·`call_id`·깨진 출력, 예산 계산, 허용 집합·`verify_cases`), `tests/test_l3_hunt.py`(프롬프트 안내·`prompt_version` 변경, 금지 문구는 기존 테스트), `tests/test_agent_config.py`(`max_input_chars`)다.
- `uv run python scripts/generate_contracts.py`와 `--check`: 통과. `frontend/`에서 `corepack pnpm install --frozen-lockfile`, `corepack pnpm contracts`, `corepack pnpm contracts:check`: 통과(37개 일치).
- **CI에서 처음 확인되는 것(이 PC에서는 Docker가 없어 `-m db`를 돌리지 못했다).** 새 `db` 테스트(`tests/test_l3_hunt_db.py`): `test_case_ids_from_the_search_result_are_kept_next_to_the_recent_cases`, `test_a_case_seen_only_in_the_search_result_is_dropped_when_the_run_did_not_search`, `test_no_data_and_error_lines_do_not_allow_a_case_id`, `test_case_ids_found_by_another_run_are_not_allowed`, `test_an_unreadable_agent_log_allows_only_the_recent_cases_and_says_so`, `test_attack_basis_and_case_search_work_in_the_same_run`, `test_verify_records_the_cases_the_run_read`, `test_verify_counts_a_search_that_found_nothing`, `test_verify_without_a_search_has_no_verify_cases_key`, `test_a_failed_verify_leaves_no_verify_cases`, `test_verify_marks_cases_unavailable_when_the_agent_log_cannot_be_read`. 바꾼 `db` 테스트: `test_too_many_tool_calls_end_the_run_without_saving_hunts`(12 → 14번). 기존 `db` 테스트(`attack_basis`, `actor_tool_calls` monkeypatch)도 새 설정(12턴)에서 다시 돈다. `store.case_search_ids`의 실제 SQL과 실제 Agent Log 행의 `output` 모양은 한 번도 실행하지 못했다(`import`만 확인).
- 실모델 확인(`-m llm`)은 하지 않았다. 이 PC에는 LLM 설정이 없다.
