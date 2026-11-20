---
issue: 344
date: 2026-11-20
owner: Pandyo
plan: 344-incident-title-recommendations.md
supersedes: []
---

# L2 분석이 Incident 제목과 권고 조치 한 목록을 만든다

## 한 일

L2 분석 출력(`incident_analysis`)이 `title`과 `recommendations`(최대 10개, 항목 `kind`·`priority`·`title`·`detail`·`rationale`)를 낸다. `detection_rules`·`response_actions`는 없어졌다. 분석이 성공하면 `analyze/store.py:save_success`가 `clean_title(analysis["title"])`을 Incident `title`에 덮어쓴다(재분석·`not_threat` 포함). 정리 결과가 `(제목 없음)`이면 이전 제목(임시 제목 또는 지난 AI 제목)을 유지한다. 권고 조치는 `incident_proposals` 행으로 저장하고(`seq`는 목록 전체 순서), `GET /api/incidents/{id}`의 `proposals`는 `분석 라운드 내림차순 → seq` 순이다. 옛 행은 마이그레이션 `0202_incident_recommendations.sql`이 옮긴다(`kind` 개명, `body`→`detail`, `title`은 본문 첫 줄 정리값, `priority`·`rationale`은 NULL, `seq`는 탐지 → 대응 순으로 다시 매김). 프롬프트(`l2_report.md`)에 제목 규칙, 사건 요약·영향, 권고 조치 규칙과 한도를 적었다. Incident 계약은 바꾸지 않았다.

## 계획과 달라진 점

- **유일 제약을 `(artifact_id, kind, seq)`에서 `(artifact_id, seq)`로 바꿨다.** 계획은 "그대로 둔다"였다. `seq`가 종류별 순번에서 목록 전체 순서로 바뀌어, 옛 행을 다시 매기려면 어차피 제약을 풀어야 했고(종류별 제약이 남으면 `UPDATE` 중간에 중복이 날 수 있다), 새 의미에는 `(artifact_id, seq)`가 맞다. 새 저장 경로는 이 제약을 어기는 행을 만들지 않는다.
- **`App.tsx`는 `p.kind === "response"`와 `<pre>{p.detail}</pre>`만 보정했다.** 계획은 "라벨은 `p.title`+`p.detail`"이었지만, `title`·`priority`·`rationale` 표시는 화면 이슈 범위라 타입이 깨지는 곳(`kind` 비교값, `body`→`detail`)만 고쳤다.
- **0202를 먼저 쓰고 그 테스트를 나중에 썼다.** 순서가 계획(샘플 → 테스트 → 코드)과 달랐다. 테스트는 마이그레이션 없이는 의미가 없는 옛 구조 행 삽입이 필요해서 실제 SQL과 함께 만들었다. 대신 옛 샘플 15개(`tests/fixtures/l2/legacy_proposals.json`)를 손으로 정한 기대값과 파이썬 `clean_title` 양쪽에 대어 보는 테스트로 SQL을 확인했다.
- **`ui_seed.json`의 `incident_proposals`를 5행으로 늘렸다.** 한 Artifact에 탐지·대응이 섞인 행(`seq` 1·2)과, 옛 구조에서 옮긴 모양(`priority`·`rationale`이 null)의 행을 넣었다. API 테스트가 쓴다.
- **`tests/test_db_tables.py`의 적용 순서 목록에 0202를 더했다.**

## 다음 사람이 알아야 할 것

- **분석 출력 `title`에는 `minLength`·`maxLength`·`pattern`이 없다.** 계약 검증이 빈·공백뿐인·긴 제목을 거부하면 보고 run이 계약 오류로 끝나는데, 이는 재시도 대상이 아니다(`_RETRYABLE_REPORT_FAILURES`는 `provider_error`·`rate_limited`·`log_error`뿐이다). `save_failure`로 가서 라운드가 올라가고 같은 Incident를 다음 사이클이 다시 분석하다가 `max_failures`에서 `held`가 된다(D-059 유형). 그래서 형식 검사는 저장 시점의 `clean_title`이 한다. 이 이유 때문에 이 필드에 제약을 더하지 않는다.
- **`recommendations`는 반대로 계약에서 거부한다.** 개수 ≤10, `title` ≤200자(+Ticket 제목과 같은 공백 pattern), `detail` ≤2000자, `rationale` ≤1000자. 모델이 한도를 자주 넘기면 분석이 실패하고 `held`까지 갈 수 있다. Foundry로 확인하지 못해 숫자는 제안값 그대로다.
- **저장 계약 `incident_proposal`은 옛 행 때문에 느슨하다.** `priority`·`rationale`은 null 허용이고 `detail`에 길이 상한이 없다(옛 `body`가 2000자를 넘을 수 있다). 길이 한도는 분석 출력 계약만 지킨다. 화면은 `priority`·`rationale`이 null일 수 있음을 처리해야 한다.
- **AI 제목은 브랜치 판단 입력에 들어간다.** `l2/branch/decide.py:_candidate_data`가 후보 Incident의 `title`을 모델에 보여 준다. 분석이 끝난 Incident는 첫 Alert 이름이 아니라 AI 제목으로 보인다(`test_branch_candidate_shows_the_ai_title_after_analysis`).
- **Incident 제목을 사람이 고치는 경로는 없다.** 재분석이 사람이 정한 제목을 덮어쓸 일은 지금 없다. 편집 기능이 생기면 재분석 때 덮어쓸지 다시 정해야 한다.
- **`U+2003` 등 공백 목록(8종) 밖 공백만 있는 제목은 그대로 저장된다**(`clean_title`·계약 pattern과 같은 기준, D-070).
- **옛 행 건수는 세지 못했다.** 서버가 내려가 있어서이다. 0202 적용 전에 사람이 `docs/plans/344-incident-title-recommendations.md`의 읽기 전용 쿼리 5개로 센다. 마이그레이션은 0건이어도 통과한다(테스트 있음). 건수: (미기록)
- **손으로 확인(Foundry)은 하지 않았다.** 실제 모델로 Incident 하나를 분석해 제목과 권고 조치가 사건과 맞는지, 한도를 넘기지 않는지, 비용이 얼마인지는 아직 모른다. 결과: (미기록)
- `rationale`은 근거 장부(`evidence_ids`) 검증 대상이 아니다. 자유 텍스트라 모델이 조사 결과에 없는 사실을 쓸 수 있다(범위 밖으로 정했다).

## 확인 방법

- `uv run ruff format --check .`, `uv run ruff check .`: 통과.
- `uv run pytest`: 2615 통과.
- `uv run pytest -m "db or qdrant"`(`DATABASE_URL`은 `.env`의 서버에서 DB 이름만 `postgres`로 바꿔 로컬 컨테이너에, `QDRANT_URL`은 로컬 컨테이너): 603 통과(경고 1건).
- `pnpm contracts:check`: 35개 일치. `pnpm lint`: 오류 없음(기존 경고 1건). `pnpm test`: 86 통과. `pnpm build`: 통과.
- 새 테스트:
  - 계약: `tests/fixtures/contracts/{valid,invalid}/incident_analysis.json`·`incident_proposal.json`(빈·긴 제목은 유효, 항목 한도 위반·옛 필드는 거부).
  - `tests/test_l2_analyze.py`: `build_records`의 순서·제목 정리·빈 목록, 프롬프트 내용.
  - `tests/test_l2_branch_db.py`(`db`): 제목 덮어쓰기·긴 제목 자르기·쓸 수 없는 제목 4종(`""`, 공백, 공백 목록뿐, 폴백 문구)이 임시 제목을 유지하고 한 라운드로 저장됨·분석 실패 시 유지·재분석 갱신·재분석에서 쓸 수 없는 제목은 지난 AI 제목 유지·`not_threat`도 갱신·항목 제목 정리·브랜치 후보의 AI 제목.
  - `tests/test_incident_recommendations_db.py`(`db`): 0202가 빈 DB와 옛 행이 있는 DB에서 적용, 15개 옛 샘플의 변환 결과(손 기대값과 파이썬 `clean_title` 모두와 일치), 변환 행이 저장 계약 통과, `seq` 다시 매김, CHECK, 공백 목록 일치.
  - `tests/test_api_ui.py`(`db`): `proposals`가 `seq` 순이고 옛 구조에서 옮긴 모양(null)도 나옴.
