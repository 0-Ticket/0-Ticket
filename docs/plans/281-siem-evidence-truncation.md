---
issue: 281
date: 2026-11-16
owner: Interludeal
supersedes: []
---

# SIEM 결과 인용 방식을 정하고, 한도보다 큰 히트가 0건으로 보이지 않게 하기

## 목표

- `query_siem` 결과의 히트 하나가 결과 한도(`max_tool_result_chars`)보다 커도 "문서는 있었지만 내용을 볼 수 없었다"를 모델이 알 수 있게 보인다. `total`은 1인데 `hits`가 0건인 결과를 만들지 않는다.
- SIEM 결과의 근거 인용은 지금처럼 호출의 `call_id`(`agl_`)로만 한다(인용-B). `siem_ref`는 근거 ID가 아니다. 계약 거부(`format_error`)는 그대로 두고, 원본 문서를 찾는 방법과 한계를 문서에 적는다.

## 방법

기준은 `5a9ab2d`가 아니라 `84ff726`(main)이다. 이슈 본문의 두 결함은 이 커밋에서도 그대로 재현된다(히트 하나 8,613자 → L1 6,000자·L2/L3 8,000자 모두 0건. `siem_ref` 모양 `evidence_ids`는 `evidence_ids[0]: pattern` 위반).

### 인용: B (D-058)

- `evidence_id` 계약(`contracts/common/types.schema.json`)과 `src/soc/l1·l2·l3/`는 바꾸지 않는다.
- 도구 설명의 "결과는 이 호출의 call_id로만 인용한다(siem_ref는 인용할 수 없다)"는 그대로 맞다. `fields_omitted` 설명 한 문장만 더한다.
- `docs/architecture.md`의 "단계끼리 주고받는 데이터" 절 끝에 "SIEM 결과 되짚기" 단락을 더하고, 변경 이력에 한 줄 적는다.
  1. Verdict의 `agl_`로 Agent Log tool 줄을 찾는다.
  2. 그 줄 `output.hits[].siem_ref`를 읽는다. `output`은 모델에게 보인 결과다(D-036, #278).
  3. 원본 문서는 둘 중 하나로 찾는다. (가) `raw_records.siem_ref`(같은 저장 키, D-049)로 찾는다. 수집된 문서에만 해당한다. (나) ELK에서 찾으려면 이스케이프를 되돌린다. `json.loads('"' + siem_ref + '"')`가 `<_index>/<_id>`를 준다. ES 색인 이름에는 `/`가 못 들어가므로 첫 `/`에서 나눈다. 코드는 `/` 분리를 가정하지 않는다(`ids.py`).
  4. 한계: 뒤에서 빠진(`omitted`) 히트의 `siem_ref`는 Agent Log에도 남지 않는다. tool 줄 `input`(조회 인자)으로 조회를 다시 해서 찾는다. 그 사이 결과가 달라질 수 있다. `fields_omitted` 히트는 `siem_ref`는 있지만 내용은 Agent Log에도 없다.
- `docs/decisions.md`에 D-058 행과 기록 줄을 더한다.

### 큰 히트 처리: 혼합 (줄이기 먼저, 못 맞추면 `siem_ref`만)

`src/soc/tools/siem.py`의 `_cap`·`_hit`·`_query_siem`을 고친다. 길이는 모두 `registry.dumped_len()`, 곧 모델에게 실제로 가는 직렬화(`_dump`: `json.dumps(ensure_ascii=False)` 뒤 `<`→`<`, `>`→`>`)의 길이로 잰다. 글자 수나 문자별 환산표로 세지 않는다. 큰따옴표·`<`·`>` 이스케이프가 늘리는 길이와, `_dump` 설정에서 늘어나는 그 밖의 문자(제어 문자 등)를 같은 방법으로 함께 막는다.

1. **`_cap`**
   - 문자열 값 하나의 `dumped_len(값)`(양쪽 따옴표 포함)이 `FIELD_MAX_CHARS`(300) 이하가 되게 자른다. 자른 값 끝에 `CUT_MARK`(`…`)를 붙이고, **표시를 포함한** 직렬화 길이가 300 이하여야 한다. 앞부분 길이는 이분 탐색으로 찾는다(`registry._shape_text`와 같은 방식). 잘리면 경로를 `truncated_fields`에 적는다.
   - 목록은 앞 `FIELD_MAX_ITEMS`(10)개만 남기고, 목록 경로를 `truncated_fields`에 적는다. 남긴 원소는 위 규칙으로 각각 자른다.
2. **한 히트의 몫(b)**
   - `몫 = (max_tool_result_chars − 빈 본문 길이) ÷ min(히트 수, HIT_SHARE_MAX)`. `HIT_SHARE_MAX`는 4로 시작한다(실측으로 확정).
   - 빈 본문은 `call_id`·머리 칸·`hits: []`·`truncated: true`·`omitted: <히트 수>`를 직렬화한 것이다.
   - 히트 하나의 `dumped_len`이 몫을 넘으면 그 히트의 `fields`를 `registry.shorten_record`(`_shorten`의 공개 이름)로 줄인다. 가장 긴 문자열부터 반으로 줄이고, 줄인 경로를 그 히트의 `truncated_fields`에 합친다.
   - 줄여도 몫에 못 맞추면 `{"siem_ref", "fields": {}, "fields_omitted": true}`로 바꾼다.
   - 이 단계는 뒤에서 빼기 **전에** 모든 히트에 적용한다. 긴 히트 하나 때문에 한도에 들어갈 다른 히트가 빠지지 않는 것이 목표다.
3. **뒤에서부터 빼기**: 지금 반복(`ctx.fits`)을 그대로 쓴다. `omitted`는 지금처럼 못 보인 히트 수다.
4. **안전망**: `siem_ref`만 있는 히트조차 안 들어가는 아주 작은 한도에서만 `hits: []`(지금 동작)다.

최상위 `truncated`는 히트를 뺐거나, 몫 때문에 줄였거나, `fields_omitted`로 바꿨으면 `true`다. `_cap` 자르기만 있으면 지금처럼 `false`이고 히트의 `truncated_fields`만 붙는다. `registry.py`에는 이름 공개 `shorten_record`와 새 함수 `dumped_len(value)`만 더한다. `_dump`는 이름을 바꾸지 않는다(테스트가 가져다 쓴다).

### 테스트 (먼저 쓴다)

- 새 샘플(손으로 만든 작은 JSON, `tests/fixtures/siem/`)
  - `search_oversized_hit.json`: 큰따옴표·`<` 번갈아 300자 값(`url.path`·`url.query`·`user_agent.original`·`host.name`)과 같은 값 3개 목록(`user.name`)을 담은 히트 하나. 본문 재현이다.
  - `search_oversized_hit_wide.json`: 필드 10개 모두 크고 `user.name`은 원소 5,000개 목록인 히트 하나(`_cap` 뒤에도 몫을 넘는 경우).
  - `search_oversized_then_small.json`: 앞에 큰 히트 1건, 뒤에 작은 히트 여러 건.
- 새 테스트(`tests/test_tools_siem.py`)
  - 큰따옴표·`<` 번갈아 값: 자른 뒤 `dumped_len(값) <= FIELD_MAX_CHARS`(표시 포함)이고 `…`로 끝난다.
  - 비ASCII 문자(한글·이모지)와 제어 문자가 섞인 값: 같은 기준을 만족하고, 자른 앞부분이 `dumped_len` 기준 가장 긴 앞부분이다.
  - 원소 5,000개 목록: 10개로 잘리고 목록 경로가 `truncated_fields`에 있다.
  - 본문 재현: `total 1`, `hits` 1건, `siem_ref` 있음, `body_chars <= 6000`(L1), 모든 필드 값의 직렬화 길이가 300 이하.
  - 필드 10개·목록 히트: 몫 안으로 줄고 `source.ip`·시각은 그대로이며 줄인 경로가 `truncated_fields`에 있다. 줄여도 안 맞는 경우는 `fields_omitted: true` + `siem_ref`.
  - 앞에 큰 히트 1건과 작은 히트 여러 건: 작은 히트가 모두 보이고 `omitted == 0`이며, 큰 히트는 줄이거나 `fields_omitted`로 보인다.
  - 줄여서 보인 결과를 `agl_`(`call_id`)로 인용한 Verdict가 계약·장부 검사를 통과한다. Agent Log tool 줄 `output.hits[].siem_ref`가 모델에게 보인 값과 같다.
- 기존 테스트
  - `test_query_with_no_room_for_one_hit_returns_zero_hits`는 지우거나 건너뛰지 않는다. `chars=300`·히트 40건의 새 동작(`fields_omitted` 히트 하나나 0건)을 개발 때 실측해 기대값을 고친다. 원래 단언(`hits == []`, `truncated true`, `omitted 40`)은 `siem_ref`도 안 들어가는 더 작은 한도로 입력을 바꿔 같은 이름의 테스트로 남긴다.
  - 길이 기준이 바뀌어 고치는 기대값: 긴 `url.query`를 자르는 테스트(`len == 301`, `tests/test_tools_siem.py` 178~180행 부근)는 `dumped_len(값) <= FIELD_MAX_CHARS`와 `…`로 끝남으로 바꾼다.
  - `test_citing_siem_ref_is_rejected`·`test_citing_alert_id_in_result_body_is_evidence_id_error`는 그대로 둔다(인용-B에서 거부가 유지되는지 확인).
- 몫 값(`HIT_SHARE_MAX`)과 `chars=300` 기대값은 개발 때 실측해 정하고, 측정값과 이유를 `docs/notes/281-siem-evidence-truncation.md`에 적는다.

## 바꿀 곳

- `src/soc/tools/siem.py`: `_cap`(직렬화 길이 기준, 목록 상한), `_hit`, `_query_siem`(몫·`fields_omitted`·안전망), 도구 설명 한 문장
- `src/soc/tools/registry.py`: `_shorten`을 `shorten_record`로 이름 공개(호출 한 곳, 동작 같음), `dumped_len` 추가(`_fits`도 이걸 쓴다)
- `tests/test_tools_siem.py`, `tests/fixtures/siem/`(샘플 세 개)
- `docs/architecture.md`(되짚기 단락, 변경 이력), `docs/decisions.md`(D-058, 기록), `docs/plans/281-siem-evidence-truncation.md`, `docs/notes/281-siem-evidence-truncation.md`

## 다른 코드와 맞물리는 곳

- `registry.shorten_record`(이름만 공개)와 `registry.dumped_len`(새 함수). 부르는 곳은 `registry.py`와 `siem.py`뿐이고 동작은 바뀌지 않는다.
- `query_siem` 결과의 히트에 `fields_omitted` 칸이 생긴다(있을 때만). 모델 입력과 Agent Log tool 줄 `output`에 들어간다. `hits[]`를 읽는 코드는 레포 안에 없다(`src/soc/l1·l2·l3`, `api`, `frontend` 확인). `siem_ref`·`truncated_fields`·`truncated` 칸의 이름은 그대로다.
- `evidence_id` 계약, 근거 장부(`runner.py`), `evidence_ids`를 읽는 L1·L2·L3 코드와 화면은 바꾸지 않는다.
- #279와의 겹침은 닫혔다. #279 계획이 "SIEM 반환 필드에서 비밀 칸 빼기"를 이미 `TARGET_FIELDS` 허용 목록으로 갈음했다. 이 이슈는 반환 필드 목록을 바꾸지 않고, `truncated_fields`·`fields_omitted`에는 필드 값 대신 경로 이름만 넣는다.

## 범위 밖

- 인용-A(`siem_ref`를 근거 ID로 허용). `evidence_id` 계약 변경과 L1~L3·화면 담당 합의가 필요해서, 필요해지면 계약 담당과 새 이슈에서 정한다.
- 뒤에서 빠진(`omitted`) 히트의 `siem_ref`를 결과에 싣는 일. `docs/notes` 기술 부채에 후속 후보로 적는다.
- `count_siem`의 값 자르기(`VALUE_MAX_CHARS`는 글자 수 기준). 같은 종류의 길이 기준이지만 히트가 숨는 문제는 없어서 건드리지 않는다. 기록에 한 줄 적는다.
- #279 범위의 일(모델 입력 가림, 반환 필드 변경).

## 완료 기준

- [ ] (C10) 한도를 넘는 히트 하나(`tests/fixtures/siem/`의 손으로 만든 샘플)가 0건으로 보이지 않고, 줄이거나 `fields_omitted`로 보이며, 모델이 "문서는 있었지만 내용을 볼 수 없었다"를 알 수 있다.
- [ ] (C10) 앞에 큰 히트 1건과 작은 히트 여러 건이면 작은 히트가 모두 보인다.
- [ ] (C10) SIEM 결과를 `agl_`로 인용한 Verdict가 계약 검사와 장부 검사를 통과한다. `siem_ref` 인용은 `format_error`로 거부되고(기존 테스트), 원본 문서를 찾는 방법과 한계가 `docs/architecture.md`에 적혀 있다.
- [ ] 값 하나의 직렬화 길이(표시 포함, 큰따옴표·`<`·`>`·비ASCII·제어 문자 포함)가 `FIELD_MAX_CHARS` 이하임을 테스트로 확인한다. 목록은 `FIELD_MAX_ITEMS`개 이하다.
- [ ] `test_query_with_no_room_for_one_hit_returns_zero_hits`는 지우거나 건너뛰지 않고 기대값만 바꿨다. 몫 값(`HIT_SHARE_MAX`)과 새 기대값의 측정값과 이유가 `docs/notes`에 있다.
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

- **인용: B.** A는 `evidence_id` 패턴을 공유하는 스키마 여섯 개와 생성 코드, 접두사로 갈리는 L1·L2·L3 코드와 화면을 바꿔야 한다. B로도 큰 히트가 보이면 `agl_` → tool 줄 → `siem_ref`로 되짚을 수 있고, A는 나중에 B 위에 더할 수 있다. D-058.
- **큰 히트: 혼합.** B(`siem_ref`만)는 `source.ip`·시각 같은 짧은 신호까지 잃으므로, 가장 긴 문자열부터 줄이는 A를 먼저 하고 바닥에서만 `siem_ref`만 남긴다.
  - 이슈 본문 "원문 300자"와 달리 `_cap`을 직렬화 뒤 길이 기준으로 한다(사람이 정함). 이스케이프가 늘리는 길이를 `_cap`에서 막는다.
  - 길이 판정은 문자별 환산표가 아니라 `dumped_len()`(실제 직렬화 길이)로 한다(사람이 정함). 비ASCII 문자나 제어 문자가 `_dump` 설정에서 늘어나는 경우도 함께 막는다.
  - 자른 값은 `…`를 포함한 직렬화 길이가 `FIELD_MAX_CHARS` 이하여야 한다(사람이 정함). 지금의 "300자 + `…` = 301자"에서 바뀐다.
  - 줄이기는 "비었을 때 첫 히트만"이 아니라 뒤에서 빼기 전에 모든 히트에 한 히트의 몫을 적용한다(사람이 정함). 몫은 `(한도 − 빈 본문) ÷ min(히트 수, 4)`로 제안했고, 값 4는 개발 때 실측해서 정한다.
- 기준 커밋 이후(`5a9ab2d` → `84ff726`) 바뀐 것: `siem_ref`가 저장 키(이스케이프된 값)가 됐다(#277), 핸들러가 데몬 스레드에서 돈다(#280, D-055), #279의 비밀 칸 제거는 허용 목록으로 이미 해결됐다. 결함 둘은 그대로다. #278 이후에도 SIEM tool 줄 `output`은 핸들러가 줄인 결과 그대로다.
- D-058과 기록 줄 "사용자가 계획을 확정함"(계약 담당 합의가 필요한 변경이 아니라서 "팀 합의(#281)"가 아니다).

## 바뀐 점

