---
issue: 344
date: 2026-11-20
owner: Pandyo
supersedes: []
---

# L2 분석 결과 정리: Incident 제목을 AI가 붙이고 대응·탐지 룰 제안을 하나로 합치기

## 목표

L2 분석이 성공하면 Incident `title`이 AI가 붙인 사건 제목(정리 후)으로 바뀌고, 대응 방안과 탐지 룰 제안이 `recommendations` 한 목록(`kind`·`priority`·`title`·`detail`·`rationale`)으로 저장·조회된다. 옛 구조로 저장된 제안은 마이그레이션 0202가 새 구조로 옮긴다. 화면은 따로 고친다.

## 방법

1. **샘플과 테스트 먼저.**
   - `tests/fixtures/l2/analyze.json`의 모델 출력 샘플을 새 구조로 바꾼다. 정상, 빈 제목, 공백뿐인 제목, 201자 넘는 제목, 개행이 낀 제목, 항목 필수 필드 누락, 잘못된 `kind`·`priority`, 11개 항목, 항목 길이 초과 케이스를 더한다.
   - 새 `tests/fixtures/l2/legacy_proposals.json`은 옛 구조 `incident_proposals` 행 샘플이다. `detection_rule`·`response_action`, 한 줄, 여러 줄, 앞에 빈 줄, CRLF, 첫 줄이 200자 이하·200자 초과, NBSP·U+3000이 낀 줄, 목록 밖 공백(U+2003)뿐인 줄, 공백 목록뿐인 본문, 코드포인트 경계(이모지)를 담고 기대값을 손으로 적는다.
   - 마이그레이션 테스트는 `tests/test_ticket_title_db.py`(0109)와 같은 방식이다. 0202만 뺀 디렉터리로 `migrate`를 돌려 옛 행을 넣고, 전체를 다시 적용한다.

2. **분석 출력 계약 (`contracts/incident_analysis.schema.json`).**
   - 필수 필드에서 `detection_rules`·`response_actions`를 빼고 `title`·`recommendations`를 더한다. 속성 순서는 verdict, title, summary, assessed_severity, techniques, impact, cause, further_risk, recommendations, evidence_ids이다. 사건을 먼저 설명하고 권고 조치가 뒤에 오게 한다.
   - **`title`은 `{"type": "string"}`만 둔다. `minLength`·`maxLength`·`pattern`을 두지 않는다.** 이유는 "토론으로 정한 것"에 적었다.
   - `recommendations`는 `maxItems 10`이고 비어 있어도 된다(`not_threat` 등). 항목은 다음과 같다.
     - `kind`: `response` | `detection`
     - `priority`: `high` | `medium` | `low`
     - `title`: 1~200자, Ticket 제목과 같은 공백 pattern(공백 8종뿐인 값 거부)
     - `detail`: 1~2000자
     - `rationale`: 1~1000자
   - 항목이 틀리면 거부한다(자르지 않는다).
   - `summary`·`impact`·`cause`·`further_risk`는 그대로 쓴다. 사건 요약·영향은 새 필드를 만들지 않는다.

3. **저장 계약 (`contracts/incident_proposal.schema.json`).**
   - `kind`는 `response` | `detection`이고 `body`를 `detail`로 바꾼다.
   - `priority`는 `high|medium|low|null`, `rationale`은 `string|null`이다. `null`은 0202가 옮긴 옛 행만 갖는다.
   - `title`은 필수이고 1~200자에 Ticket 제목과 같은 pattern이다.
   - `detail`은 `minLength 1`뿐이고 `maxLength`는 두지 않는다. 옛 `body`가 2000자를 넘을 수 있어서이다. 길이 한도는 분석 출력 계약만 지킨다.
   - 계약 이름(`IncidentProposal`)과 테이블 이름(`incident_proposals`), API 응답 필드 `proposals`는 그대로 둔다.
   - `seq`는 합쳐진 목록 전체의 순서(1..n)이다. `(artifact_id, kind, seq)` 유일 제약은 그대로 둔다.
   - `scripts/generate_contracts.py`·`pnpm contracts`로 Python·TS 생성물을 다시 만든다(D-003).

4. **제목 저장 (`src/soc/l2/analyze/store.py`).**
   - `save_success`가 `clean_title(analysis["title"])`을 구한다(`soc.ticketing`, #343). 결과가 `FALLBACK_TITLE`이면(빈 값, 공백 8종뿐, 모델이 폴백 문구를 그대로 낸 경우 포함) `incident["title"]`을 유지하고, 아니면 `updated["title"]`에 넣는다.
   - `_update_incident` UPDATE에 `title`을 더한다. 재분석 때도 같은 코드를 지나므로 갱신된다.
   - 판정이 `not_threat`이어서 `dismissed`가 되어도 같다.
   - 분석 실패(`save_failure`)는 제목에 손대지 않는다.
   - Incident 계약(`incident.schema.json`)은 바꾸지 않는다.
   - 제안 항목의 `title`은 저장 시 `clean_title`로 정리한다(공백·개행 한 칸). 계약에서 이미 1~200자와 pattern을 확인했으므로 폴백은 나오지 않는다.

5. **제안 저장 (`build_records`, `_insert_proposal`).** `recommendations`를 순서대로 `incident_proposals` 행으로 만든다(`kind`·`priority`·`title`·`detail`·`rationale`, `seq`는 목록 전체 순서). `incident_proposal` 계약 검증은 지금처럼 저장 전에 한다.

6. **마이그레이션 `0202_incident_recommendations.sql`**(0201 다음, 실행기가 파일마다 트랜잭션). 집합 연산뿐이라 행이 0건이어도 통과한다.
   1. `kind` CHECK를 떼고 `detection_rule`→`detection`, `response_action`→`response`로 UPDATE한 뒤 새 CHECK(`response`, `detection`)를 건다.
   2. `body`를 `detail`로 이름을 바꾼다(`body <> ''` CHECK는 컬럼을 따라간다).
   3. `priority text NULL`(CHECK `high|medium|low`), `rationale text NULL`, `title text`(nullable)를 더한다.
   4. `title` 백필: `detail`에서 앞쪽 공백 목록(`[\t\n\v\f\r  　]`)을 떼고, 첫 줄바꿈(`\n`·`\r`) 앞까지 자른 첫 줄에 `clean_title`과 같은 정리를 SQL로 한다(공백 연속 → 한 칸, 앞뒤 한 칸 제거, 200자 넘으면 앞 199자 + `…`, 목록 밖 글자가 없으면 `(제목 없음)`). 0109와 같은 정규식 목록과 자르기를 쓴다.
   5. `title`을 NOT NULL로 하고 CHECK(0109와 같은 pattern)를 건다.
   - 옛 행의 `priority`·`rationale`은 `NULL`로 둔다. 값을 지어서 채우지 않는다.

7. **API.**
   - `GET /incidents/{id}`(`routes/workflow.py`)의 `proposals` 조회 정렬을 `a.analysis_round DESC, p.seq`로 바꾼다(`kind` 정렬 제거).
   - 응답 모델은 계약 `IncidentProposal`을 그대로 쓰므로 `ui_models.py`는 바뀌지 않는다.
   - `IncidentItem`은 바꾸지 않는다(`title`은 이미 있고 `proposals`는 상세에만 있다).
   - `frontend/src/api/generated/`를 `pnpm contracts`로 다시 만든다.

8. **프롬프트 (`src/soc/l2/prompts/l2_report.md`).**
   - 제목 규칙: 공격 유형과 대상(또는 출발지)이 드러나는 한 줄이다. ID·룰 코드만 나열하지 않는다.
   - 사건을 먼저 설명한다: `summary`(무엇이, 언제, 어디서, 어떻게), `impact`(영향받은 자산과 심각도 판단 이유).
   - `recommendations`: `kind`와 `priority` 기준. `detail`은 구체적인 조치이고, 탐지 룰이면 룰 내용을 `detail`에 쓴다(기존 `detection_rules` 문자열이 가지던 내용). `rationale`은 이 사건의 어떤 사실 때문에 필요한지 쓴다. 개수·길이 한도를 적는다. 조치는 실행하지 않고 제안으로만 쓴다.
   - 기존 규칙(verdict, 자산 조회 실패 시 추정 금지)은 유지한다. "탐지 제안과 대응 제안" 문장은 새 구조로 바꾼다.

9. **기존 입력·화면 호환.**
   - `l2/analyze/context.py`의 `previous_artifact`에는 제안이 들어가지 않으므로 바뀌지 않는다.
   - `App.tsx`의 `p.kind === "response_action"`은 `"response"`로, 라벨은 `p.title`+`p.detail`로 최소 보정한다(타입 검사가 깨지는 곳만, 화면 동작은 유지). `App.test.tsx`와 `ui_seed.json`·`dev_seed` 시드의 `incident_proposals`, `contracts/valid·invalid`, `tests/contract_samples.py`를 새 구조로 보정한다.

10. **브랜치 판단 입력 변화 확인.** `l2/branch/decide.py:_candidate_data`는 코드를 바꾸지 않는다. 새 테스트 하나(`tests/test_l2_branch_db.py`, `db`)로 분석 성공 후 같은 Incident를 후보로 만들면 `title`이 AI 제목이고 `ticket_count`·`paths` 등 나머지는 그대로임을 확인한다.

11. **결정 기록.** `docs/decisions.md`에 D-072(Incident 제목 규칙, 권고 조치 구조)를 "확정"과 "기록"에 더한다. D-045를 가리키되 D-045는 고치지 않는다(원칙 8).

12. **손으로 확인(Foundry).** 실제 모델로 Incident 하나를 분석해 제목과 권고 조치가 사건과 맞는지 본다. 결과와 비용을 `docs/notes/`에 적는다. 키와 환경은 사람이 준비하며, 개발 때 어떤 Incident로 돌릴지 묻는다.

## 바꿀 곳

- `contracts/incident_analysis.schema.json`, `contracts/incident_proposal.schema.json`, `src/soc/contracts/generated/*`(재생성), `frontend/src/api/generated/*`(재생성)
- `src/soc/l2/analyze/store.py`: 제목 저장, `build_records`, `_insert_proposal`, `_update_incident`
- `src/soc/l2/prompts/l2_report.md`
- `src/soc/db/migrations/0202_incident_recommendations.sql`
- `src/soc/api/routes/workflow.py`: 정렬
- `frontend/src/App.tsx`(타입 보정만), `frontend/src/App.test.tsx`
- `tests/`: 완료 기준의 테스트와 시드·픽스처(`tests/fixtures/api/ui_seed.json`, `tests/fixtures/l2/analyze.json`, `tests/fixtures/l2/legacy_proposals.json`, `tests/fixtures/contracts/valid·invalid/incident_analysis.json`, `incident_proposal.json`, `tests/contract_samples.py`, `tests/test_l2_analyze.py`, `test_l2_branch_db.py`, `test_lab_cycle_db.py`)
- `docs/decisions.md`, `docs/plans/344-incident-title-recommendations.md`, `docs/notes/344-incident-title-recommendations.md`

## 다른 코드와 맞물리는 곳

- **`incident_analysis` 계약**(L2 보고 run의 출력): `detection_rules`·`response_actions`가 사라지고 `title`·`recommendations`가 필수로 생긴다. L2 담당 확인 대상이다.
- **`incident_proposal` 계약과 `incident_proposals` 테이블**: `kind` 값, `body`→`detail`, 필수 `title`, 널 허용 `priority`·`rationale`. 읽는 코드는 L2 저장, `GET /incidents/{id}`, `App.tsx`, 시드뿐이다. UI 담당 확인 대상이다. L1·L3는 읽는 코드가 없다.
- **`GET /incidents/{id}` 응답의 `proposals`**: 항목 모양이 바뀌고(`kind`·`detail`·`title`·`priority`·`rationale`) 정렬이 `seq` 순이다. 생성 TS 타입이 바뀐다.
- **`incidents.title`**: 분석이 끝나면 AI 제목으로 바뀐다. 이 값을 읽는 `l2/branch/decide.py`의 후보 Incident 입력(브랜치 판단 LLM)이 바뀐다.
- `incident.schema.json`, `incident_artifact` 계약, 설정 키: 바꾸지 않는다.

## 범위 밖

- 화면 수정(제목·권고 조치 표시, 우선순위 정렬·라벨). `App.tsx`는 타입이 깨지는 곳만 보정한다.
- 제안의 채택·기각 기능(D-045 그대로).
- Incident 제목을 사람이 편집하는 기능. 지금 코드에 없다. 생기면 재분석 덮어쓰기를 다시 정한다.
- `recommendations`의 `rationale`을 근거 장부(`evidence_ids`)로 검증하는 것. 이번에는 자유 텍스트이다.
- 옛 Artifact(`incident_artifacts`)의 보고서 내용 변경.

## 완료 기준

- [ ] 분석 출력에 `title`이 있고, 분석 성공 시 Incident `title`이 `clean_title` 정리 후 값으로 바뀌는 테스트(가짜 모델, `db`)
- [ ] 분석 전 임시 제목(첫 Alert 제목)이 유지되고, 분석 실패·빈 제목·공백 8종뿐인 제목·폴백 문구면 임시 제목이 유지되는 테스트
- [ ] 빈 제목·공백뿐인 제목·201자 이상 제목·개행이 낀 제목을 줘도 계약 오류가 나지 않고 라운드가 한 번에 성공으로 저장되며 같은 Incident를 다시 분석하지 않는 `db` 테스트
- [ ] 재분석 때 제목이 갱신되는 테스트, `not_threat`로 `dismissed`가 돼도 갱신되는 테스트
- [ ] `recommendations` 항목의 필수 필드·`kind`·`priority` 값·길이·개수(11개)를 검증하고 틀린 출력은 거부하는 테스트
- [ ] 대응·탐지 항목이 한 목록에 섞여 `seq` 순으로 저장되고, 탐지 항목의 `detail`에 룰 내용이 보존되는 테스트(`db`)
- [ ] 프롬프트에 제목 규칙, 사건 요약·영향, 근거(`rationale`) 작성 규칙, 한도가 들어 있고 이를 확인하는 테스트
- [ ] 마이그레이션 0202가 빈 `incident_proposals`(0건)와 옛 구조 행이 있는 DB 모두에서 적용되는 `db` 테스트
- [ ] 옛 구조 샘플 행(`legacy_proposals.json`)이 0202 적용 후 기대값과 같은 `db` 테스트: `kind` 개명, `detail`=옛 `body`, `title`=첫 줄 정리값(200자 초과·폴백·개행 변형 포함), `priority`·`rationale`=NULL
- [ ] 같은 샘플 첫 줄에 파이썬 `clean_title`을 적용한 값과 SQL 백필 결과가 같은 `db` 테스트(코드포인트 경계, NBSP·U+3000, U+2003은 폴백이 아님)
- [ ] 저장 계약이 `priority`·`rationale`의 `null`을 허용하고 새 분석 출력은 그 둘이 필수·비어 있지 않음을 확인하는 계약 테스트
- [ ] `GET /incidents/{id}`의 `proposals`가 새 구조이고 `seq` 순인 API 테스트, 프론트 생성 타입 갱신, `App.tsx`·`App.test.tsx`·시드 보정, `pnpm contracts:check`·`pnpm lint`·`pnpm test`·`pnpm build` 통과
- [ ] 분석 성공 후 후보 Incident의 브랜치 입력 `title`이 AI 제목인 L2 브랜치 테스트
- [ ] L2·UI 담당 승인(계획 확정 전). L1·L3는 "읽는 코드가 없다"는 알림만(승인 요구 아님)
- [ ] 손으로 확인(Foundry): 실제 모델로 Incident 하나를 분석해 제목과 권고 조치가 사건과 맞는지 보고, 결과와 비용을 `docs/notes/`에 적었다
- [ ] 0202 적용 전에 사람이 옛 행 건수를 센다(아래 쿼리). 결과를 `docs/notes/`에 적었다
- [ ] `docs/decisions.md`에 D-072(Incident 제목 규칙, 권고 조치 구조), 기록 줄
- [ ] 키·비밀 값이 코드, 테스트, 로그, notes, PR에 없다
- [ ] `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run pytest -m "db or qdrant"` 통과
- [ ] `docs/plans/`에 확정 계획, `docs/notes/`에 개발 기록

## 토론으로 정한 것

이슈 본문과 달라진 점, 질문과 답:

- **저장 위치**: `recommendations`는 Incident 계약이 아니라 기존 `incident_proposals` 행에 둔다. 이슈의 "정식 필드냐 `details`냐"는 둘 다 아니다. Incident 계약(`incident.schema.json`)은 바꾸지 않는다. D-045의 행 단위 설계를 유지한다(나중에 채택·기각). `details`는 다른 단계가 읽지 않는 칸이다.
- **이름**: 저장·API 이름은 그대로(`incident_proposals`·`IncidentProposal`·`proposals`), 분석 출력 필드만 `recommendations`이다. 개명은 테이블·계약·생성 타입·API·프론트로 번져 이번 목적에 비해 크다.
- **값 표기**: `kind`는 `response`/`detection`(이슈대로), `priority`는 `high`/`medium`/`low`(기존 `verdict`·`status`·`kind`가 영문 enum, 화면 라벨은 화면 이슈에서 한글로, 사람이 정함).
- **한도**: 개수 ≤10, 항목 `title` ≤200자, `detail` ≤2000자, `rationale` ≤1000자. 넘으면 거부하고 기존 실패 경로를 탄다(자르면 탐지 룰 내용이 말없이 잘려 의미가 바뀐다). 숫자는 제안값을 사람이 받아들였다.
- **분석 출력 `title`에는 `minLength`·`maxLength`·`pattern`을 두지 않고, 정리는 저장 시점에 `clean_title`로 한다.** 이유: 계약 검증은 모델 출력을 받는 곳이라 여기서 빈 제목·공백뿐인 제목·200자 넘는 제목을 거부하면 보고 run이 계약 오류로 끝난다. 계약 오류는 재시도 없이 `save_failure`로 가서 라운드가 올라가고(`_RETRYABLE_REPORT_FAILURES`는 `provider_error`·`rate_limited`·`log_error`뿐이다), Incident는 `analyzing`에 남아 같은 건을 다음 사이클이 다시 분석하며, 연속 실패가 `max_failures`에 이르면 `held`가 된다(D-059 유형). 제목은 사건 분석의 부수 값이라 제목 때문에 분석 전체를 버리면 안 된다. 그래서 형식 검사는 저장 시점의 `clean_title`이 하고, 쓸 수 없는 값(폴백)이면 임시 제목을 유지한다. 목록 항목(`recommendations`)은 본문이므로 반대로 계약에서 거부한다.
- **재분석·`not_threat` 제목 갱신**: 분석이 성공하면 판정과 상관없이 갱신한다. 지금 제목을 편집하는 경로가 없어 덮어써도 사람이 고친 값을 잃지 않는다.
- **브랜치 판단 입력 변화 수용**: 후보 Incident의 `title`이 첫 Alert 이름에서 AI 제목으로 바뀌어 브랜치 판단 LLM 입력이 달라진다. 받아들이고, 이 변화를 확인하는 L2 브랜치 테스트 하나를 더한다(사람이 정함).
- **옛 행 처리**: 마이그레이션 0202로 변환한다. `kind` 개명, `body`→`detail`, `title`은 본문 첫 줄을 `clean_title`과 같은 규칙으로, `priority`·`rationale`은 NULL로 둔다. 값을 지어서 채우지 않으며(원칙 3), 저장 계약만 이 둘의 `null`을 허용한다(분석 출력 계약은 필수). 마이그레이션은 행 수와 무관하게 동작하고 0건이어도 통과한다. 파이썬 기대값과의 일치는 옛 구조 샘플 행으로 만든 `db` 테스트가 지킨다(사람이 정함). 서버가 내려가 있어 옛 행 건수는 아직 모른다. 건수는 서버가 올라온 뒤 0202 적용 전에 사람이 센다.
- **담당자 승인**: L2·UI 담당 승인을 확정 전에 받는다. L1·L3에는 "읽는 코드가 없다"는 것만 댓글로 알린다. 이슈 완료 기준의 "L1·L2·L3·UI 전원 승인"에서 달라진 점이다.
- **결정 목록**: D-072로 올린다. D-045는 고치지 않고 가리킨다(원칙 8).

0202 적용 전에 사람이 읽기 전용으로 건수를 세는 쿼리(건수만 기록한다):

```sql
-- 1) kind별 옛 제안 수
SELECT kind, count(*) FROM incident_proposals GROUP BY kind;

-- 2) Artifact 라운드 수와, 제안이 붙은 Artifact 수
SELECT count(*) AS artifacts,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM incident_proposals p WHERE p.artifact_id = a.id)) AS with_proposals
FROM incident_artifacts a;

-- 3) 첫 줄이 200자를 넘어 잘릴 행
SELECT count(*) FROM incident_proposals
WHERE char_length(split_part(regexp_replace(body, '^[\t\n\v\f\r  　]+', ''),
                             E'\n', 1)) > 200;

-- 4) 공백 목록 밖 글자가 없어 폴백이 될 행
SELECT count(*) FROM incident_proposals
WHERE body !~ E'[^\\t\\n\\u000b\\f\\r \\u00a0\\u3000]';

-- 5) body가 2000자를 넘는 행 (저장 계약에 detail 길이 상한이 없는 이유)
SELECT count(*) FROM incident_proposals WHERE char_length(body) > 2000;
```

## 바뀐 점

