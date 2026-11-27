---
issue: 389
date: 2026-11-27
owner: Pandyo
plan: 389-attack-actor-tool.md
supersedes: []
---

# L3 가설 생성이 ATT&CK 그룹·악성코드·캠페인의 기법을 이름으로 조회하고, 코드가 관계 근거를 기록하게 했다

## 한 일

- `uv run python -m soc.l3.intel`이 ATT&CK 그룹·악성코드·캠페인(폐기·대체 제외, 도구(tool) 제외)과 기법으로 가는 `uses` 관계를 새 표 `attack_actors`·`attack_actor_techniques`(0308)에 저장한다. 같은 버전을 다시 받으면 그 버전의 행을 지우고 다시 넣는다. 기법만 저장돼 있고 새 표가 빈 버전도 다음 수집에서 다시 받아 채운다.
- 읽기 전용 도구 `get_attack_actor`가 영어 이름·별칭(대소문자만 무시, 정확히 같아야 함)으로 행위자를 찾아 기법을 돌려준다. `[tools.local_intel] log_data_components`와 겹치는 탐지 데이터 소스가 많은 순(같으면 기법 ID 순)으로 한 호출에 최대 20개다. 결과가 `max_tool_result_chars`를 넘으면 기법을 뒤에서부터 빼고(`omitted`), 그래도 넘으면 행위자를 뒤에서부터 뺀다(`actors_omitted`). 허용 단계는 `l3`뿐이고 읽기 역할에 새 표 SELECT를 줬다(0309).
- 가설 생성 run은 프롬프트(`l3_hypothesize.md`) 안내대로 뉴스에서 읽은 이름으로 이 도구를 부를 수 있다(호출은 최대 5번이라고 프롬프트에만 적었다). run이 끝나면 `hypothesize()`가 그 run의 Agent Log tool 줄을 읽어, 가설 기법 중 도구 결과에 실린 것과 근거 행위자를 `details.sources.attack_basis`에 `grounded`로, 나머지를 `model_only`로 적는다.
- 도구를 한 번도 안 부른 run의 Hunt는 예전과 같다(`attack_basis`가 없다).

## 계획과 달라진 점

- **`attack_basis`는 도구를 한 번 이상 부른 run에만 쓴다.** 계획은 "가설마다 기록"이었지만 완료 기준의 "도구를 안 부르면 기존 동작·저장 결과 유지"와 맞추려고 호출이 0번이면 키를 넣지 않는다. 키가 없으면 도구를 안 부른 것이다. Agent Log를 못 읽으면 `{"unavailable": true}`다.
- `parse_attack`은 그대로 두고 기법과 행위자를 함께 돌려주는 `parse_attack_bundle`을 새로 만들었다(`parse_attack`은 그 앞부분만 돌려준다). 번들을 두 번 파싱하지 않으려는 것이다. 행위자의 ATT&CK ID·별칭 모양이 틀리면 그 출처 전체가 `parse` 실패라 `parse_attack`도 같은 입력에서 실패한다.
- 수집 결과 줄(`format_results`)과 `SourceResult`는 바꾸지 않았다. 행위자 건수는 출력에 나오지 않는다.
- 도구의 `actors` 목록 상한은 새 설정 없이 기존 `[tools.local_intel] list_max_items`(20)를 같이 쓴다.
- 새 설정 키(`log_data_components`, `actor_techniques_max`)는 `get_attack_actor`의 설정 검사에서만 읽는다. 기존 세 도구의 설정 검사는 그대로라 새 키가 없는 설정도 그 도구들에서는 오류가 아니다.
- `tests/fixtures/l3_intel/attack.json`은 기존 객체 순서를 그대로 두고(인덱스를 쓰는 기존 테스트 때문에) 가짜 행위자·관계를 뒤에 더했다. 인덱스 5의 `intrusion-set`은 ATT&CK ID(G0001)와 이름("Alpha Group")을 받았다. 다시 저장하면서 줄 모양이 바뀌어 diff가 크다.
- 실제 모델 확인을 하기 위한 테스트(`tests/test_l3_hunt_actor_llm.py`)와 손으로 만든 샘플 뉴스(`tests/fixtures/l3_hunt/actor_news.json`)를 더했다. 이 환경에는 LLM 설정이 없어 실행하지 못했다(아래).

## 다음 사람이 알아야 할 것

- **실제 모델 확인은 하지 않았다.** 완료 기준의 "손으로 만든 샘플 뉴스로 실제 모델을 한 번 돌려 도구 호출 여부와 검증 run의 호출 여부를 적는다"는 비어 있다. LLM 키와 `config/local.toml`의 `[llm]`이 있는 곳에서 `DATABASE_URL=… LLM_API_KEY=… uv run pytest -m llm -s tests/test_l3_hunt_actor_llm.py`로 돌리면 가설 생성 run의 도구 호출 수와 부른 이름, `attack_basis`, 검증 run의 도구 호출 수가 한 줄씩 나온다. 결과를 이 기록에 건수로 적어야 한다.
- **가설 생성 run의 실패 비용.** 도구를 너무 많이 불러 모델 호출이 `[agent.l3] max_turns`(10, 검증 run과 공유)를 넘으면 `budget_exceeded`로 끝나고 Hunt가 하나도 저장되지 않는다. 이 run도 시도로 세어 다음 시도가 `[l3.hunt] generate_interval_seconds`(86400초) 뒤다. 코드 상한은 없고 프롬프트의 "최대 5번"에만 기댄다. 가짜 모델로는 도구 9번+답이 10턴으로 통과했고 도구 12번은 `budget_exceeded`였다. 형식 오류 재요청까지 합치면 여유가 없다.
- **검증 run에도 보인다.** 도구 허용이 stage로만 정해져 `[tools.allowed].l3`의 `get_attack_actor`가 L3 검증 run에도 붙는다. 이번에는 허용했고 `attack_basis`는 가설 생성 run의 `run_id`만 읽는다. 검증 run이 부르는지는 위 실제 확인에서 센다.
- **이름은 정확히 같아야 한다.** 실제 20.0 번들에서 "Lazarus Group"은 찾아지지만 "lazarus"는 `not_found`다(별칭에 없다). "ShinyHunters"·"Akira"(그룹 G1024와 악성코드 S1129에 함께 걸림)·"Cobalt Strike"·"Sandworm Team"·"APT28"은 찾아지고, "Page"는 악성코드 Elise(S0081)의 별칭이라 `found`다. 모델이 일반 단어를 부르면 오탐 근거가 생길 수 있다는 점은 프롬프트("뉴스에 이름이 나왔다는 것이 우리 환경에서 일어났다는 뜻은 아니다")로만 막는다.
- **근거는 run 단위다.** 한 run의 도구 결과에 실린 기법이면 그 run의 모든 가설에서 `grounded`다. 어느 뉴스 때문에 부른 호출인지는 가르지 않는다. 지금은 `max_hypotheses = 1`이다.
- **#382와 맞물리는 곳.** `docs/decisions.md`, `[tools.allowed].l3`, `src/soc/tools/__init__.py`, 도구 이름 기대값 테스트(`tests/test_agent_config.py`, `tests/test_tools_registry.py`), `l3_hypothesize.md`가 겹칠 수 있다. `log_data_components`는 #382로 SIEM 직접 조회가 되면 로그 소스에 맞게 다시 본다(설정이라 코드 변경은 없다). `AgentTask`·`AgentResult`·계약은 바꾸지 않았다.
- **`config/local.toml`에서 `[tools.allowed].l3`를 따로 정의한 곳**은 `get_attack_actor`를 직접 더해야 한다. `[tools.local_intel]`을 따로 정의했으면 `log_data_components`·`actor_techniques_max`도 있어야 한다(없으면 이 도구를 쓰는 run이 시작 전에 도구 설정 오류로 끝난다).
- **마이그레이션 뒤 수집을 한 번 돌려야 한다.** 이미 저장된 20.0은 새 표가 비어 있어 그 전까지 도구가 `no_data`(`attack_actors_not_collected`)를 돌려준다. 수집은 새 표가 비었으면 같은 버전도 다시 받는다(약 55MB).
- 도구가 읽는 이름은 별칭에 이름 자신을 뺀 것이다. 이름과 별칭은 DB의 `lower()`로 같음 비교를 한다(비 ASCII 대소문자는 DB 정렬 규칙을 따른다).
- 폐기·대체된 행위자 이름은 저장하지 않으므로, 뉴스에 옛 이름이 나오면 `not_found`다.
- 그룹이 쓰는 악성코드의 기법은 그룹에 합치지 않는다. 그룹 쪽 기법이 0개인 행위자는 `found`와 빈 `techniques`다(실제 20.0에서 5개).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과
- `uv run pytest`: 2745건 통과
- `uv run pytest -m db`(임시 PostgreSQL 17.6 컨테이너, 이 작업을 위해 따로 띄우고 끝낸 뒤 지움): 748건 통과, 2건 실패. 실패 2건은 `tests/test_l2_branch_db.py`의 `qdrant` 마커도 붙은 테스트가 `QDRANT_URL`이 없어 실패한 것이다(이 이슈와 무관, Qdrant를 띄우지 않았다).
- 주요 테스트
  - `tests/test_l3_intel.py`: 폐기·대체 행위자와 폐기된 관계 제외, 별칭에서 이름 자신 제외, 틀린 행위자 모양은 `parse` 실패
  - `tests/test_l3_intel_db.py`: 새 표 저장, 기법만 있던 버전 다시 받기, 두 번째 수집에서 행 교체·중복 없음, 새 버전 누적, 실패 시 그대로, CHECK·외래키
  - `tests/test_tools_attack_actor.py`: 이름·별칭 일치 입력, 정렬과 20개 상한, 여러 행위자 합치기, `not_found`·`no_data`, 큰 샘플에서 호출이 실패하지 않고 `omitted`·`actors_omitted`가 남음, 잘못된 입력은 DB에 닿지 않음, 설정 오류
  - `tests/test_tools_local_intel_db.py`(`db`): 읽기 역할로 읽기·쓰기 거부, 이름·별칭 일치와 단어 일부·와일드카드 불일치, 로그 겹침 우선 정렬, 같은 이름의 두 행위자, `no_data`, 다른 단계에는 안 붙음
  - `tests/test_l3_hunt_db.py`(`db`): `attack_basis`의 `grounded`·`model_only`, 결과 없는 호출도 호출 수에 셈, 도구를 안 부르면 키 없음, 다른 run의 호출은 안 셈, Agent Log를 못 읽으면 Hunt를 저장하고 `unavailable`, 도구를 과하게 부르면 `budget_exceeded`
  - `tests/test_agent_config.py`·`tests/test_tools_registry.py`·`tests/test_db_tables.py`·`tests/test_tools_db.py`: 기대값만 고침(도구 이름, 표 목록, 읽기 권한 목록)
- 2026-11-27 공개 피드로 코드 이름 일치를 쟀을 때(이 이슈의 방향을 바꾼 측정, 건수만): 보안뉴스 0/50, The Hacker News 3/50(진짜 1), KEV 109/1805(거의 전부 오탐), 가설 생성 입력(최근 5건) 모의 35건에서 일치 0건·KEV 10건.
- 실제 ATT&CK 20.0 번들로 손으로 확인(임시 DB, 건수만): 행위자 981개(그룹 178, 악성코드 747, 캠페인 57), `uses` 관계 16767건, 별칭 700개, 기법 706개. 파싱 약 0.7초, 파싱 단계 최대 상주 메모리 약 290MB. `log_data_components` 시작값 5개(Network Traffic Content, Network Traffic Flow, Network Connection Creation, Application Log Content, Response Content)는 모두 저장된 `detection_sources`에 있다. 5개와 겹치는 기법은 706개 중 311개다. 도구 결과는 이름에 따라 약 2700~4100자(한도 8000자 안)이고 호출은 약 0.02~0.03초다.
