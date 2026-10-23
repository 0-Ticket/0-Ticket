# 웹 화면

SOC 분석가가 에이전트의 판정과 조사 과정을 보고, 검토하고 승인하는 화면이다. 화면 형태는 결정 대장 D-013(웹)을 따른다.

화면 작업을 할 때는 이 문서와 `docs/api-contracts.md`를 함께 읽는다. 보안 규칙은 `docs/security-policy.md` 7항이다.

## 화면이 하는 일과 하지 않는 일

| 한다 | 하지 않는다 |
|---|---|
| 티켓, Incident, Case, 헌팅 결과, 룰 제안과 그 근거를 보여 준다 | 판정, 우선순위, 묶음을 스스로 계산한다 (코어가 한다) |
| 에이전트가 무엇을 조회하고 어떻게 판단했는지(Agent Log) 보여 준다 | LLM, SIEM, DB를 직접 부른다 |
| 사람의 검토 입력(동의/뒤집기, 승인/반려)을 받아 API로 보낸다 | 차단·격리·계정 잠금 같은 대응을 실행한다 (범위 밖) |
| 지표(뒤집은 비율, 반려 유형 통계, 정규화 실패)를 보여 준다 | 데이터 계약에 없는 필드를 만들어 쓴다 |

검토 입력의 검증(뒤집을 때 이유 필수 등)은 화면에서도 막지만, 최종 검증은 코어가 한다. 화면의 검증만 믿지 않는다.

## 흐름

화면은 아래 흐름을 보여 준다. 박스 번호는 `docs/architecture.md`(v2)를 따른다.

```
외부 SIEM(1개) → 커넥터(3) → 원본 Alert·Event(6·7) → OCSF(4) → Lookup(5) → 엔티티 분기(25)
  엔티티 분기(25) ─ Incident에 존재 → 기존 Incident 추가 + L2 재실행
                  ├─ 공격 대상 시나리오 → 시나리오 티켓(10)
                  └─ 그 외 → L1 엔티티 조회(11) ─ 확신도 ≥ 임계값 → L1 승격 티켓(10)
                                                └ 미만 → 보류 → L3 데이터 풀
시나리오·L1 승격 티켓 → 증거 요청(26) → 전문가(13·14) + MCP(15) → L1 판정(11)
  ├─ 오탐 · 확신도 ≥ 임계값 → 종결
  ├─ 이상 행위 · 확신도 ≥ 임계값 → L2 승격 → 엔티티 분기(25, L2 입구)
  └─ 확신도 미만 · LLM 실패 · 큐 실패 → 보류 → L3 데이터 풀
L1 결과 조회(27): 사람은 승격·보류·판정 결과와 증거 요청 실패를 읽기만 한다

Incident(18) ⇄ L2(19) → Incident Artifact(20) + 룰 제안(24) · 대응 방안 → Slack 알림 → 승인 · 확정(21) → Case(22)
                ▲                                                                      │ 반려(사유) → L2 재분석, 2회면 사람 처리
L3 헌팅(23) ← 운영자 시나리오 · Case · 보류 건 ─ 위협 존재 → L3 승격 티켓 → 엔티티 분기(25, L2 입구)
```

정규화부터 L1 판정까지는 완전 자동이다. 사람은 L1 결과를 27에서 읽기만 하고, 승인은 21(승인 · 확정)에서만 한다. F1과 F2는 #73에서 v2에 맞췄다(읽기 전용 L1 결과 조회, 판정 뒤집기 제거). 아래 화면 중 F3의 Correlation 출처 표시와 F5 룰 승인은 아직 v1 흐름 기준이다. v2에 맞추는 일은 후속 이슈로 하고, 그전까지 그 화면의 기존 동작을 유지한다.

## 화면 목록

순서대로 만들고, 각 화면은 처음부터 최종 형태로 만든다. 순서의 근거는 `docs/architecture.md` "구현 순서"의 화면 트랙이다.

| 순서 | 화면 | 경로 | 쓰는 계약 | 관련 박스 | 주 사용자 |
|---|---|---|---|---|---|
| F0 | 프론트 기반 | | 전체 계약 타입 | | |
| F1 | L1 결과 조회 (읽기 전용) | `/review` | C23, C6, C5, C7, C4 | 5, 10, 11, 26, 27 | L1 분석가 |
| F1 | 알럿 L1 상세 (읽기 전용) | `/alerts/:alert_id` | C5, C4, C21, C23, C22, C8 | 11, 25, 26, 27 | L1 분석가 |
| F1 | 티켓 목록 | `/tickets` | C6, C5 | 5, 10 | L1 분석가 |
| F2 | 티켓 상세 (읽기 전용) | `/tickets/:ticket_id` | C6, C5, C4, C7, C23, C22, C14, C8, C9 | 5, 10 ~ 15, 26, 27 | L1 분석가 |
| F3 | Incident 목록 | `/incidents` | C10 | 18 | L2 분석가 |
| F3 | Incident 상세 | `/incidents/:incident_id` | C10, C6, C17, C11, C8, C15 | 18 ~ 21 | L2 분석가 |
| F4 | Case 목록 · 상세 | `/cases`, `/cases/:case_id` | C16 | 22 | L2 분석가 |
| F5 | 헌팅 결과 | `/hunts`, `/hunts/:hunt_id` | C17, C8 | 23 | 탐지 엔지니어 |
| F5 | 룰 제안 | `/rules`, `/rules/:proposal_id` | C18, C17, C16 | 24 | 탐지 엔지니어 |
| F6 | 운영·지표 대시보드 | `/` | 지표 응답, C6, C10, C16, C17, C18 | 4, 10, 18 ~ 24 | 전체, 운영자 |

- F0은 폴더, 도구, 계약 타입, API 호출 계층, mock, CI를 만든다. 화면은 만들지 않는다.
- F1은 읽기 전용 L1 결과 조회(27)다. 알럿 결정 목록(C23)과 티켓 목록을 한 화면에 두고, 알럿 ID는 알럿 L1 상세로, 티켓 ID는 F2로 간다. L1 결과를 바꾸는 동작은 없다. v2 L1은 `awaiting_human` 티켓을 만들지 않으므로 검토 대기 건수도 표시하지 않는다.

## 화면별 표시 규칙

### 공통

- 상태, 판정, 심각도는 배지로 보여 준다. 값과 라벨·색의 대응은 한 곳에서만 정의한다.
- 심각도 `severity_id`(0 ~ 6) 라벨: 0 Unknown, 1 Informational, 2 Low, 3 Medium, 4 High, 5 Critical, 6 Fatal
- 시간(epoch 밀리초)은 브라우저 지역 시간으로 보여 주고, 원래 값은 툴팁에 둔다.
- ID는 복사할 수 있게 하고, 해당 객체 화면으로 링크한다.
- `extensions`는 키-값 표로 그대로 보여 준다. 화면 코드에서 특정 키를 해석하지 않는다.
- 등록형 값(`handling_type`, `specialist`, `attack_type`, Entity `type`, Evidence `ref_type`, Ioc `type`)은 화면 코드에 목록을 고정하지 않는다. 아는 값은 라벨로, 모르는 값은 원래 문자열로 보여 준다. 플러그인이 새 값을 등록해도 화면이 깨지지 않게 하기 위해서다.
- 선택 필드가 `null`이면 "없음"으로 보여 준다. 빈칸으로 두지 않는다.

### Lookup 정보 (F1, F2)

- 알럿(C5)의 `src_asset`, `dst_asset`, `user_info`를 보여 준다.
  - 자산: `hostname`, `criticality`(1 ~ 5), `owner`, `zone`, `shared`
  - 계정: `user`, `dept`, `privileged`
- 모르는 IP(`null`)는 "자산 정보 없음"으로 표시한다.
- `shared`가 `true`인 공용 자산은 따로 표시한다. 엔티티 분기(25)에서 공용 엔티티로 빼는 자산이다.
- 목록의 기본 정렬은 티켓 `priority`(심각도 × 대상 자산 중요도) 내림차순이다.

### 판정과 근거 (F2)

- C7의 `verdict`, `confidence`, `summary`를 맨 위에 보여 준다.
- `recommended_action`에는 "권고 · 실행하지 않음" 표시를 붙인다.
- `evidence`마다 `ref_type`, `ref_id`, `note`를 보여 주고, 누르면 그 알럿·이벤트·원문을 펼치거나 해당 화면으로 간다.
- `needs_human`이 `true`면 `human_reason`을 눈에 띄게 보여 준다.
- 전문 에이전트 결과(C14)는 판정 근거 옆에 둔다. `succeeded`, `attack_type`, `confidence`, `summary`, 근거를 보여 준다.

### 조사 과정 (F2, F3, F5)

- C8 AgentStep을 `subject_id`별로 `step` 순서의 타임라인으로 보여 준다.
- 단계마다 `agent`, `action`, `tool`, `model`, `tokens`, `latency_ms`를 보여 준다.
- `input_excerpt`, `output_excerpt`는 접어 두고, 펼치면 텍스트로만 보여 준다.

### Correlation과 Incident (F3, v1 기준)

- 묶음 항목(`members`)은 티켓(`member_type`이 `ticket`)과 헌팅 결과(`hunt`)가 섞일 수 있다. 종류에 따라 티켓 화면 또는 헌팅 화면으로 링크한다.
- 항목마다 출처(`source`: L1 판정, 사람 확정, L3)를 배지로 보여 준다.
- 항목마다 `rule`(Correlation 규칙 ID, 사람이 묶었으면 `manual`)과 `matched_entity`(예: 같은 출발지 `203.0.113.10`)를 보여 준다.
- `excluded`가 `true`인 항목은 따로 모아 `excluded_reason`과 함께 보여 준다.
- `created_by`가 `manual`이면 사람이 직접 묶은 Incident로 표시한다.
- 티켓 상세(F2)와 헌팅 상세(F5)에서는 그 항목이 속한 Incident로 가는 링크를 둔다.

### 헌팅 결과와 룰 제안 (F5)

- 헌팅 결과(C17)는 `hypothesis`, `method`, `techniques`, `severity_id`, `query_summary`, 근거를 보여 준다. 이상 징후면 묶인 Incident로 링크한다.
- 룰 제안(C18)은 근거가 헌팅 결과(`hunt_id`)인지 Case(`case_id`)인지 보여 주고 해당 화면으로 링크한다.
- `sigma_rule`, `siem_query`는 고정폭 텍스트로만 보여 준다.

### 보고서 (F3)

- C11 `timeline`을 시간순으로 보여 주고, 항목마다 전술·기법과 근거 링크를 단다.
- `affected_assets`, `iocs`, `suspected_cause`를 보여 준다.
- `recommendations`는 `risk`와 `reversible`을 함께 보여 준다. 실행 버튼은 두지 않는다.

## 검토 동작

| 동작 | 화면 | 보내는 값 | 필수 입력 | 남는 계약 |
|---|---|---|---|---|
| L2 승인 / 반려 | F3 | `decision` (`approve`, `reject`) | 반려면 `reject_type`과 `comment` | C15 L2Review |
| 룰 승인 / 반려 | F5 | `decision` (`approve`, `reject`) | 없음 | C18 `status` |
| Case 작업 수정 | F4 | 작업 상태, 담당자, 마감, 교훈 | 없음 | C16 Case |

- L1 판정을 바꾸는 검토 동작은 없다(#73에서 제거). C9 HumanReview는 계약에만 남아 있고(발표 후 삭제), F2는 받은 기록을 읽기만 한다.
- C15의 `round`는 화면이 계산하지 않는다. 코어가 정해 돌려준다.
- L2 검토 폼은 C10 `review_state`가 `awaiting_review`일 때만 연다. `analyzing`, `approved`, `human_handling`에서는 닫고 이유를 보여 준다. `status`나 Case 유무로 판단하지 않는다(#21).
- 요청의 `expected_review_round`에는 받은 C10 `review_round`를 그대로 넣는다. 회차를 계산하지 않는다.
- 검토 건수, C15 `round`, C11 `generated_at`, 그 밖의 시각으로 새 검토 기회를 추론하지 않는다. 새 기회는 다시 조회한 C10 값으로만 알며, 새 기회가 열리면 폼을 새로 연다.
- 제출 중과 답한 기회에서는 다시 제출하지 못하게 한다(재조회가 끝나기 전 중복 클릭 포함).
- "사람 직접 처리"는 `review_state`가 `human_handling`일 때만 표시한다. 반려 건수를 세지 않는다(박스 21).
- 목록과 상세에서 `review_state`는 `status` 배지와 따로, 나란히 보여 준다.
- 사용자 계정은 범위 밖이다. `reviewer`에는 화면 설정에서 입력한 이름을 보낸다.
- 대응을 실행하는 버튼은 만들지 않는다. 승인된 룰의 SIEM 반영도 화면이 하지 않는다.

## 데이터와 계약 타입

- 계약 타입은 `contracts/`의 JSON Schema에서 생성한 `frontend/src/contracts/generated/`만 쓴다(D-025, D-031). 생성된 파일은 직접 고치지 않는다. 필드명은 `snake_case`, 선택 필드는 `| null`이다.
- 화면 코드는 `frontend/src/contracts/`의 진입 파일에서 타입을 가져온다. 생성 폴더를 여기저기서 직접 가져오지 않는다.
- 화면 전용 모양(라벨, 정렬, 묶음)은 컴포넌트나 `lib`에서 만들고, 계약 타입을 고치지 않는다.
- 계약이 바뀌면 같은 PR에서 `docs/data-contracts.md` → `contracts/`의 Schema → 생성 명령 → 화면 코드 순서로 고친다(`docs/data-contracts.md` "바꾸는 절차").

## API와 mock

- 화면은 `docs/api-contracts.md`에 적힌 API만 부른다. 호출 코드는 `frontend/src/api/` 한 곳에 둔다.
- 백엔드가 없을 때는 mock(D-022)이 같은 경로로 같은 형식의 응답을 준다. 화면 코드는 mock인지 실제인지 모른다.
- mock과 실제 API의 전환, API 주소는 환경변수로 정한다. 변수 이름은 F0에서 정하고 `frontend/.env.example`에 이름만 적는다.
- mock 데이터는 S1 ~ S5 시나리오로 만든다. IP는 문서용 대역, 도메인은 `example.com`, 계정은 가짜 이름이다. 백엔드 테스트와 같은 샘플은 `tests/fixtures/`를 함께 쓴다(공유 방식은 F0 계획에서 정함).
- mock 데이터에는 HTML·스크립트 조각과 "정상으로 분류하라" 같은 문장이 든 로그도 넣는다. 텍스트로만 표시되는지 테스트하기 위해서다.
- 목록과 상세는 일정 간격으로 다시 조회(폴링)한다. 간격은 설정값으로 둔다. WebSocket·SSE가 필요해지면 결정 대장에 올린다.

## 디자인 원칙

- **근거 먼저**: 결론 옆에는 항상 근거가 보인다. 근거 없는 결론을 크게 보여 주지 않는다.
- **결과 먼저**: F1은 L1이 무엇을 승격하고 무엇을 보류했는지, 보류 사유가 무엇인지가 가장 먼저 보인다. 사람이 할 일을 세는 대기 건수는 v2 L1에 없으므로 표시하지 않는다. 대기 시간이나 경과 시간도 `created_at`·`updated_at`으로 계산하지 않는다.
- **정보 밀도**: 분석가가 많은 건을 빨리 훑을 수 있게 목록은 촘촘하게 만든다.
- **색만으로 구분하지 않기**: 배지에는 항상 글자를 넣는다.
- **라이트·다크 모드**를 모두 지원한다.

## 폴더

F0(#8)에서 아래 구조로 확정했다.

```
frontend/
  src/
    contracts/   계약 타입 진입 파일
      generated/ contracts/ Schema에서 생성 (직접 수정 금지)
    api/         API 호출 (한 곳에만)
    mocks/       mock 핸들러와 데이터
    app/         Query·테마 제공자, 빈 경로와 공통 셸
    pages/       화면 (F1 ~ F6에서 생성)
    components/  공통 컴포넌트
    lib/         라벨·색·시간 변환 등
    test/        Vitest 초기화 (브라우저와 같은 mock 핸들러)
  .env.example   환경변수 이름만
```

### F0 실행 환경과 설정

Node **24 메이저**를 사용한다. `frontend/.nvmrc`는 `24`, `package.json`의
`engines.node`는 `>=24 <25`다. pnpm은 `packageManager`의 `pnpm@11.9.0`과
`pnpm-lock.yaml`로 고정한다. 계약 생성 도구(`tools/contracts/`)와 두 CI 검사 작업도
Node 24를 사용한다. Node 버전 전환 도구를 쓴다면 `frontend/`에서 `nvm use` 후 설치한다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_USE_MOCK` | 개발 `true`, 빌드 `false` | `true` 또는 `false` 하나로 MSW 사용 여부를 전환 |
| `VITE_API_BASE_URL` | `/api` | API 접두어까지 포함한 공개 주소. 실제 API 서버 주소로 바꿀 수 있음 |
| `VITE_POLL_INTERVAL_MS` | `30000` | Query 목록·상세 조회 기본 폴링 간격, 양의 정수 밀리초 |
| `API_PROXY_TARGET` | `http://127.0.0.1:8000` | 개발 서버가 `/api`를 넘길 결과 API 주소(http·https). `VITE_` 접두어가 없어 브라우저 번들에 들어가지 않는다. 기본값은 `config/default.toml` `[api]`와 같다 |

`.env.example`에는 이름만 두고 값은 비운다. 로컬 설정은 커밋하지 않는
`frontend/.env.local`에 쓴다. 빈 값은 기본값을 따른다. Vite 환경변수는 빌드 시 결정되므로
배포 주소를 바꾸면 다시 빌드한다. 여기에 비밀 값을 넣지 않는다.
개발 서버는 두 방법으로 띄운다(#97).

- mock(기본): `pnpm dev`. MSW가 `/api`를 받는다.
- 실제 API: `uv run python -m soc.api`를 띄우고 `VITE_USE_MOCK=false pnpm dev`. 개발 서버(`vite.config.ts`
  `server.proxy`)가 `/api`를 경로 그대로 `API_PROXY_TARGET`으로 넘긴다. 화면은 상대 경로 `/api`를 같은 출처로
  부르므로 API에 CORS를 넣지 않는다. `VITE_API_BASE_URL`은 비워 둔다. 다른 출처 주소를 넣으면 CORS가 필요하다.
- 배포용 빌드의 프록시·CORS는 정하지 않았다(#97 범위 밖).

F0의 셸은 제목과 테마 전환만 제공하고 업무 경로는 비워 둔다.
API 함수는 `src/api/endpoints.ts`, HTTP 오류는 `ApiError`로 모은다.
API 응답의 계약 타입은 생성 코드의 진입점에서 가져온다. TypeScript 타입 단언은
런타임 검증이 아니며, 실제 서버의 계약 검증은 `soc.contracts.validate_contract()`가 맡는다.
ESLint가 진입점 밖 생성 폴더 import, API 폴더 밖 직접 요청, HTML 주입을 제한한다.

### 공유 샘플과 mock

- `tests/fixtures/frontend/scenarios.json`은 S1~S5를 위한 손으로 만든 최소 객체 모음이다.
  기존 계약 샘플을 바탕으로 웹·클라우드·새 등록형 값과 연결 ID를 구성했다.
  `api-responses.json`은 페이지·지표, `api-errors.json`은 네 오류,
  `untrusted-text.json`은 텍스트 표시 보안 사례를 담는다.
- Python 테스트와 MSW는 이 JSON 파일을 직접 읽는다. 프론트 폴더에 샘플 사본을 두지 않는다.
  Vite 개발 서버는 프론트 폴더와 해당 공유 샘플 폴더만 접근 허용한다.
- `tests/frontend/test_fixtures.py`가 공개 계약 검증 함수로 객체를 검증하고 참조 ID를 확인한다.
  Vitest가 실제 HTTP 요청을 MSW로 보내 문서의 19개 메서드·경로와 응답 묶음을 확인한다.
- 브라우저와 Vitest는 `src/mocks/handlers.ts`를 공유한다. MSW worker 준비 후 앱을 시작하며,
  `VITE_USE_MOCK=false`이면 worker 모듈을 불러오지 않는다.
- 고정 버전 MSW 3.0.3의 옵션 이름은 `onUnhandledFrame`이다. 브라우저는 `bypass`,
  테스트 서버는 `error`로 설정한다. MSW 2의 `onUnhandledRequest`에서 이름이 바뀌었다
  ([공식 마이그레이션](https://mswjs.io/docs/migrations/2.x-to-3.x)).
  브라우저 시작 함수와 테스트 대역은 설치된 MSW 타입에서 유도한다.
  테스트 서버의 최초 시작·재시작 뒤 미등록 요청이 MSW 오류로 차단되는지 확인한다.
- mock의 목록은 필터·커서·기본 50/최대 200을 지원하고 검토·Case 수정은 메모리에만 남는다.
  새로고침 및 테스트 종료 시 초기화한다. 지표는 고정된 합성 집계이며 기간별 실제 집계는 하지 않는다.
  검토 오류와 처리 충돌을 흉내 낼 뿐, 코어 검증·상태 전이·분석 기능의 구현을 대신하지 않는다.
- `public/mockServiceWorker.js`는 설치된 MSW의 `pnpm exec msw init public --save`로 생성한다.
  MSW 버전을 바꾸면 같은 명령으로 갱신한다.
- F0의 텍스트 표시 테스트는 공통 `PlainText`의 안전성을 확인한다. F1~F6은 각 화면의
  실제 데이터 표시·검토 동작을 별도로 검증해야 한다.

API 요청 취소는 fetch 단계와 응답 본문 읽기 단계 모두에서 원래 `AbortError`를 그대로
전달한다. 오류 객체의 `name`을 확인하여 다른 realm의 오류도 구분한다. JSON 파싱 실패나
그 밖의 본문 읽기 실패는 기존대로 `ApiError('internal')`로 전달한다.

UI 기반은 [shadcn/ui 수동 구성](https://ui.shadcn.com/docs/installation/manual)의
로컬 컴포넌트·별칭·CSS 변수 구조를 사용하며, mock 시작은
[MSW 시작 API](https://mswjs.io/api/setup-worker/start)를 따른다.

## 명령

모두 `frontend/` 폴더에서 실행한다. 스크립트 이름은 여기서 정하고, 실제 스크립트는 F0에서 `package.json`에 만든다. F0이 끝나기 전에는 화면 코드를 만들지 않는다.

| 하는 일 | 명령 | 도구 |
|---|---|---|
| 의존성 설치 | `pnpm install --frozen-lockfile` | pnpm (D-024) |
| 개발 서버 (mock) | `pnpm dev` | Vite (D-018), MSW (D-022) |
| 타입 검사 | `pnpm typecheck` | TypeScript |
| 린트 | `pnpm lint` | ESLint (D-030) |
| 포맷 검사 | `pnpm format:check` | Prettier (D-030). 고치지 않고 검사만 |
| 테스트 | `pnpm test` | Vitest + Testing Library (D-023) |
| 빌드 | `pnpm build` | Vite |

계약 타입 생성 명령은 `docs/data-contracts.md` "계약 Schema"에 있다.

F0에서 CI에 화면 검사 작업을 추가한다. `frontend/`나 `contracts/`가 바뀐 PR에서 위 명령을 설치부터 빌드까지 차례로 돌린다.

## 완료 기준 (화면 작업)

`AGENTS.md`의 완료 기준에 더해 아래를 만족한다.

1. 위 표의 타입 검사, 린트, 포맷 검사, 테스트, 빌드가 통과한다.
2. mock 데이터로 그 화면이 "흐름"대로 동작한다.
3. 로그 원문, LLM 출력, `extensions` 값이 텍스트로만 표시되는지 테스트가 있다.
4. 검토 동작이 있는 화면은 필수 입력이 없으면 보내지 않는 테스트가 있다.
5. `tests/checklist.md`의 화면 항목을 확인하고 표시했다.


### F1 목록 조회 (#10)

- F1은 읽기 전용이다. C7은 `C6.verdict`로 받으며 판정 전에는 `null`이다.
- 티켓 목록은 API가 보장하는 `priority` 내림차순 → `created_at` 오름차순 →
  `ticket_id` 오름차순을 그대로 표시한다. 클라이언트에서 재정렬하지 않는다.
- 다음 페이지는 `next_cursor`로 “더 보기” 요청 시 가져온다. 폴링은 이미 불러온
  모든 페이지를 첫 페이지부터 새 커서로 다시 조회한다.
- 대기 건수는 `GET /api/metrics`의 `tickets_awaiting_human`이다. 목록을 모두 조회해
  세지 않는다. `from`·`to`는 지역 날짜 시작과 조회 시각을 epoch ms로 전달하며,
  현재 대기 건수의 의미는 기간과 무관하게 유지한다.
- 표시된 티켓의 자산·계정 정보는 기존 알럿 조회 API로 가져오며 알럿 ID별 Query
  캐시를 공유한다. 조회 실패는 null 자산과 구분해 오류와 재시도를 표시한다.
- 티켓 ID는 `/tickets/:ticket_id`로 연결한다. 상세 화면, L1 검토 입력과 검토자
  이름 설정은 F2에서 구현한다.


### C6 검토 대기 진입 시각 (#12)

C6 Ticket의 `awaiting_human_at`은 F1/F2가 향후 검토 대기 진입 시각으로 사용할 수 있는
UTC epoch ms 필드다. 아직 진입하지 않았다면 null이며, 대기 상태를 벗어나도 값을 유지한다.
현재 상태 전이에는 재진입 경로가 없다. null을 `created_at`이나 `updated_at`으로 대체하지 않는다.

#12에서는 계약과 생성 타입만 추가한다. F1은 현재 대기 건수만 표시하는 기존 동작을 유지하며,
F1/F2의 시각 표시·대기 시간 계산, 검토 완료 시각·소요 시간 계산은 구현하지 않는다.
향후 표시를 구현할 때 시각은 공통 지역 시간·원본 epoch ms 툴팁 규칙을 따른다.

### F2 티켓 상세와 L1 검토 (#15)

- `/tickets/:ticket_id`는 기존 `GET /api/tickets/{ticket_id}` 응답을 사용한다.
  C6은 `ticket`, C7은 `ticket.verdict`, C5·C4는 `alerts`와 그 안의 Lookup,
  C14는 `findings`, C8은 `steps`, 기존 C9는 `reviews`에서 받는다.
  Incident 링크는 응답의 `incident_ids`만 사용한다. 별도 판정·전문 결과·조사 단계·검토
  조회 API나 계약 필드를 추가하지 않는다.
- 근거의 `alert`, `event`, `raw`만 문서의 기존 조회 API로 펼친다. 알 수 없는
  `ref_type`은 문자열·ID·설명을 보존하고 조회 경로를 추측하지 않는다. ID는 복사할 수 있다.
  로그 URL은 자동 링크로 바꾸지 않는다. 전문 결과·원문·발췌·확장 값은 plain text다.
- Agent Log는 `subject_id`별 `step` 오름차순으로 표시하고, 발췌문은 접어 둔다.
  `awaiting_human_at`은 null이면 “없음”, 값이 있으면 지역 시간과 epoch ms 툴팁을 제공한다.
  다른 시각으로 보완하거나 경과·검토 소요 시간을 계산하지 않는다.
- 검토자 이름은 검토 폼에서 입력한다. 동의 버튼은 기존 TP/FP를 선택하며, 요청은
  `reviewer`, `decision` (`tp` 또는 `fp`), `reason`만 보낸다. 다른 판정 선택 시 이유를
  요구하는 것은 화면 편의 검증이다. unknown 또는 판정 없음은 TP/FP 선택과 이유가 필요하다.
  `overturned`는 계산·전송하지 않고 응답 C9의 값만 표시한다.
- 검토 성공 후 현재 상세, 두 F1 목록의 `tickets` Query, 관련 `metrics` Query만
  invalidate/refetch한다. 클라이언트에서 Ticket 상태를 계산하거나 캐시에 직접 쓰지 않는다.
  POST 자동 재시도와 중복 제출을 막고, conflict이면 같은 Query들을 재조회한다.
  검토 성공 후 GET 실패는 저장 실패와 구분하고 GET 재시도만 제공한다.
- 기존 MSW가 검토 기록과 Ticket 상태를 갱신한다. 지표의 현재 대기 건수만 mock의
  현재 티켓 상태에서 얻도록 변경했다. 나머지 기간별 합성 지표는 기존 고정값이다.
  검토 후에도 `awaiting_human_at`은 보존한다. 실제 코어 상태 전이 구현은 후속 박스 범위다.
- `tests/fixtures/frontend/ticket-detail.json`은 기존 공유 객체를 바탕으로 만든 상세 응답이다.
  브라우저 mock은 이 파일의 전문 결과와 조사 단계를 사용하고 기존 F1 티켓 집합은 유지한다.
  Python은 공개 계약 검증 함수로 샘플을 검증하며, Vitest는 상세·입력 검증·오류·재조회와
  F1 연계를 확인한다. F3 Incident 화면은 기존 예약 경로로 연결된다.

### F3 Incident 목록·상세와 L2 검토 (#17)

- `/incidents`는 `GET /api/incidents`의 응답 순서를 그대로 쓰고 `next_cursor`로 "더 보기"를
  한다. `/incidents/:incident_id`는 기존 Incident 상세 응답만 쓴다. 관련 티켓은 F1 목록
  컴포넌트와 기존 알럿 조회로 Lookup을 보여 준다. 헌팅 결과·Case는 예약 경로
  `/hunts/:hunt_id`, `/cases/:case_id`로 링크한다.
- 묶음 항목은 `excluded`로만 나눠 포함·제외 항목을 표시한다. 묶음 기준은 계산하지 않는다.
  C11 `timeline`은 계약상 시간순이므로 응답 순서 그대로 표시한다. 근거 `ticket`은
  티켓 화면으로 링크하고, 모르는 `ref_type`에는 경로를 만들지 않는다. IOC URL은
  복사만 할 수 있다. 권고에는 "권고 · 실행하지 않음"을 붙이고 실행 버튼을 두지 않는다.
- 응답 C15에서 `decision=reject`가 2건 이상이면 "사람 직접 처리"를 표시한다. 문서의 표시
  규칙을 위한 파생 표시이며 상태 값이나 검토 가능 여부를 정하지 않는다.
- 검토 폼은 `case_id`가 있거나 `closed_benign`·`escalated_to_case`일 때만 비활성화한다.
  별도의 검토 가능 상태를 정의하지 않고, 최종 판단은 API의 `conflict`에 맡긴다.
  요청은 `reviewer`, `decision`, `reject_type`, `comment`만 보낸다. 반려 유형·코멘트 필수는
  화면 편의 검증이다. `round`, Incident 상태, Case 생성 여부는 계산하거나 보내지 않는다.
  성공·conflict 후 상세, Incident 목록, 지표 Query만 다시 조회한다. POST는 자동 재시도하지 않는다.
- mock은 기존처럼 L2Review를 기록하고 `round`를 정한다. 상태 전이와 Case 생성은
  흉내 내지 않는다(박스 21·22 후속). Case가 있거나 `closed_benign`·`escalated_to_case`인
  Incident의 검토 요청에는 `conflict`를 준다. `tests/fixtures/frontend/incident-detail.json`의
  Incident·헌팅·보고서·조사 단계·검토 기록을 기존 시나리오에 더해 쓴다.

#### L2 재검토 동작과 한계 (#17)

> #21에서 대체됨. 아래와 위 #17 기록(종결 상태·Case로 폼 비활성, 세션당 1회 mock, 같은 화면 성공 후 영구 잠금)은
> 이력으로만 남긴다. 지금 규칙은 "검토 동작"의 C10 `review_state`·`review_round` 항목과 `docs/api-contracts.md`
> "L2 검토 기회 (#21)"다.

- 정책: 같은 Incident에 C15가 여러 건 생길 수 있다(`round`, 박스 21). 반려되면 L2가 다시
  분석하고, 코어가 새 검토 기회를 열면 다시 검토한다. `round`는 코어가 정한다.
- 현재 계약·API에는 "새 검토 기회가 열렸다"를 알려 주는 신호가 없다. C10 상태에 검토 대기가
  없고, C11에는 회차가 없으며, C15는 검토한 보고서를 참조하지 않는다. 그래서 화면과 mock은
  검토 건수, `round`, `generated_at`·`created_at` 비교로 새 회차를 추론하지 않는다.
- 화면: `case_id`나 종결 상태에서만 폼을 비활성화한다. 같은 화면에서 검토가 성공하면 폼을
  다시 열지 않는다. 다른 화면에 갔다 오거나 새로고침하면 다시 열리고, 그때 가능 여부는
  API가 `conflict`로 판단한다. 같은 기회의 중복 제출은 화면의 제출 잠금과 API `conflict`로 막는다.
- mock: 위 종결 조건 외에는 "세션마다 Incident당 검토 1회"로 단순화했다. 재분석과 다음
  회차는 흉내 내지 않는다. 기존 검토 기록이 있다는 이유만으로 막지는 않는다.
- 새 검토 기회 신호는 후속 이슈 #21 "[Contract] Incident L2 재검토 가능 상태 신호 정의"에서
  계약 변경 절차로 정한다. 정해지면 화면과 mock은 그 신호만으로 폼과 `conflict`를 판단한다.

### F0~F3 화면 스타일 정리 (#20)

- 제공된 UI 디자인(Figma Make 시안)의 시각 언어만 가져왔다. 시안의 코드·가짜 데이터는 쓰지 않았고,
  API·계약·Query·mock·검토 검증·상태 판단은 바꾸지 않았다. 새 패키지는 없다.
- 색은 `src/styles.css`의 CSS 변수(라이트 `:root`, 다크 `.dark`)를 Tailwind 테마 색으로 연결해 쓴다.
  의미 색은 `critical`·`warning`·`success`·`info`·`purple`과 각각의 `-soft` 배경이다.
- 값 → 라벨·색(tone) 대응은 계속 `src/lib/display.ts` 한 곳에 둔다(`badges`, `severityTones`,
  `riskTones`, `toneRails`). 배지는 항상 글자를 넣고 `data-tone`으로 색을 표시한다.
  모르는 값은 원래 문자열을 `neutral` 색으로 보여 준다.
- 공통 부품: `components/ui/`의 `Button`(ghost·icon 크기 추가), `ToneBadge`, `Card`·`Section`(제목이 있는
  region), `Input`·`Textarea`·`NativeSelect`·`FieldLabel`; `components/`의 `Icon`(인라인 SVG, 장식용
  `aria-hidden`), `PageHeader`, `Breadcrumbs`, `ReviewPanel`·`Choice`·`FormMessage`.
- 셸: 왼쪽 사이드바(좁은 화면에서는 위쪽 가로 메뉴)와 테마 전환. 상세 화면은 `위치` 경로 링크
  (`티켓 목록`, `Incident 목록`)와 본문 + 오른쪽 고정 검토 폼 2열이다.
- `/review`는 대기 건수 카드, 강조 테두리, 검토 사유 강조로 할 일을 먼저 보이게 하고,
  `/tickets`는 같은 목록을 전체 조회용으로 보여 준다. 표시 필드·순서·조회는 같다.
- 디자인에는 있으나 계약·API에 없어 넣지 않은 것: P1/P2 등급과 우선순위 색, 퍼센트 확신도,
  경과·대기 시간, 우선순위별·Incident 개요 건수, 상단 환경·시계·근무조, 분석가 계정,
  검색·필터·정렬·페이지 번호·전체 건수, 내보내기·Incident 연결 버튼, 결정 기본 선택,
  L1 승인/반려, 시안의 반려 유형, `details` 키 해석, 로그 수준 색 구분, 멤버 "MATCH REASON",
  보고서 상태 배지·요약(EXECUTIVE SUMMARY)·타임라인 색, 전술 이름 대응표, 권고 제목 분리.
  필요하면 계약 변경 절차를 거친 별도 이슈로 다룬다.
- `/`(F6 대시보드)는 이번 범위가 아니라 셸만 보였다. #31에서 구현했다.

### F4 Case 목록·상세와 작업 상태 변경 (#27)

- `/cases`는 `GET /api/cases`의 응답 순서를 그대로 쓰고 `next_cursor`로 "더 보기"를 한다.
  행마다 Case ID, 상태, 제목, 관련 Incident 링크, 작업 담당자(`tasks[].owner`, 중복 제거),
  작업 수, 작업 상태별 건수, `created_at`, `closed_at`을 보여 준다. 상태별 건수는 받은 `tasks`를
  표시용으로 센 값일 뿐이며 Case 상태·진행률·완료 여부·우선순위를 정하지 않는다.
  목록에서는 Incident 상세를 건별로 조회하지 않는다.
- `/cases/:case_id`는 `GET /api/cases/{case_id}`의 `case`와 `proposal_ids`를 쓴다. 관련 Incident로
  링크하고, 룰 제안은 예약 경로 `/rules/:proposal_id`로만 링크한다(F5 미구현).
  `lessons`는 표시만 하며 null이면 "없음"이다. `extensions`는 기존 키-값 표로 보여 준다.
- Case 상세 응답에는 C11이 없어서, 상세 화면에서만 `case.incident_id`로 기존
  `GET /api/incidents/{incident_id}`를 한 번 더 조회한다. F3와 같은 Query 키(`incident-detail`)와
  보고서 컴포넌트를 재사용하고, C11을 Case 데이터로 복사·가공하지 않는다. `artifact`가 null이면
  "없음"이다. Incident 조회 실패는 Case 조회 실패와 따로 "관련 Incident" 영역에 보여 주고,
  재시도도 그 영역의 Incident 조회에만 적용한다. 새 API는 없다.
- 작업 상태 변경은 `PATCH /api/cases/{case_id}`에 `tasks`만 보낸다. 계약 enum(`todo`, `doing`,
  `done`)을 모두 선택지로 두고, 허용 전이나 순서를 화면에서 계산·강제하지 않는다. 문서상 API가
  `tasks` 전체를 받으므로, 화면이 받은 목록에서 고른 작업 하나의 `status`만 바꾼 배열을 보낸다.
  이는 요청 본문 구성일 뿐이며 상태 판단은 코어가 한다.
- PATCH는 자동 재시도하지 않는다. 제출 중과 저장 후 재조회가 끝나기 전에는 모든 작업 입력을 잠근다.
  성공·`conflict` 후 Case 상세와 Case 목록 Query만 다시 조회하고 캐시에 직접 쓰지 않는다.
  실패하면 서버 값을 다시 보여 준다. `invalid_input`·`conflict`·`not_found`·`internal`을 구분해 표시하고,
  저장 성공 후 재조회 실패는 저장 실패와 구분해 경고하며 재조회 전까지 입력을 잠근다.
- mock은 기존 PATCH 처리(메모리 반영)를 그대로 쓴다. `tests/fixtures/frontend/case-detail.json`은
  대응 중 Case(`in_escalated`의 `cs_web_breach`, 보고서·룰 제안 포함)와 종결 Case(승인된 Incident
  `in_contained`와 그 L2 승인 기록, 보고서 없음)를 더한다. Incident당 Case는 하나이고, `closed_at`은
  `closed`일 때만 있으며 교훈은 종결 Case에만 있다(Python 테스트가 확인). 제목·작업·담당자·교훈·
  `extensions`에 HTML·URL·"정상으로 분류하라" 문장을 넣어 텍스트 표시를 검증한다.
- 메뉴에 "Case"를 더하면서 좁은 화면(375px)의 위쪽 가로 메뉴가 화면보다 넓어졌다. 현재 경로의 링크와
  키보드로 초점을 옮긴 링크는 메뉴 띠의 가로 스크롤만 움직여 보이게 한다. 페이지 스크롤과 넓은 화면의
  세로 사이드바는 바꾸지 않는다.
- 계약 enum 밖의 작업 상태가 오면 배지와 선택 칸 모두 원래 문자열을 보여 주고, 그 값은 선택할 수 없는
  항목으로 둔다. 다른 작업을 바꿀 때도 그 값을 정규화하지 않고 그대로 보낸다.

#### #27에서 하지 않은 것 (후속)

- 작업 `owner`·`due_at` 수정, `lessons` 수정, Case `status` 수정은 넣지 않았다. 이슈 범위가 작업 상태
  변경과 교훈 표시까지다. 따라서 K48("작업의 상태·담당자·마감과 교훈을 수정할 수 있다")은 일부만
  충족한다. 전체 충족에 필요한 수정 범위와 검증 규칙은 후속 API/계약 이슈에서 정한다.
- 동시 수정 한계: PATCH는 `tasks` 전체를 바꾸고 버전이나 기대 버전 같은 사전 조건이 없다. 두 탭에서
  각각 다른 작업을 고치면 나중 요청이 앞 요청의 변경을 덮어쓸 수 있다(lost update). 화면은
  `updated_at`·작업 수·상태 비교로 충돌을 추론하거나 병합하지 않고, 임의 version 필드도 만들지 않는다.
  후속 이슈 후보: "[Contract] Case Task 수정 동시성 제어 정의" — 낙관적 동시성 신호(version 또는
  expected version 계열)를 검토한다.

### F5 헌팅 결과·룰 제안 (#29)

- `/hunts`, `/rules`는 `GET /api/hunts`, `GET /api/rules`의 응답 순서를 그대로 쓰고 `next_cursor`로 "더 보기"를 한다.
  헌팅 행은 ID, 심각도, 이상 징후 여부(`is_anomaly`), `method`, 사람 확인 필요, 가설, 기법, 근거 건수,
  `incident_id` 링크(null이면 "없음"), `rule_candidate`, `created_at`을 보여 준다. 룰 제안 행은 ID, `status`,
  `syntax_ok`, 사람 확인 필요, 제목, 기법, `hunt_id`·`case_id` 링크, 검토자, 백테스트 건수, `created_at`을 보여 준다.
  목록에서는 헌팅·Case·Incident 상세를 건별로 조회하지 않는다(N+1 없음).
- `/hunts/:hunt_id`는 헌팅 상세 응답(`hunt`, `steps`, `proposal_ids`)만 쓴다. 가설, 기법, `query_summary`,
  근거(기존 근거 목록: `event`는 기존 `GET /api/events/{id}`로 펼치고, 모르는 `ref_type`은 원래 문자열과 복사 가능한
  ID만), `needs_human`·`human_reason`, Incident 링크, Agent Log, 룰 제안 링크를 보여 준다.
- `/rules/:proposal_id`는 C18만 받는다. `sigma_rule`, `siem_query`는 고정폭 텍스트 블록이며 문법 강조를 하지 않는다.
  `syntax_ok=false`, `siem_query=null`, `backtest=null`은 받은 그대로("문법 검사 실패", "없음") 보여 준다.
  백테스트는 받은 기간과 `attack_hits`·`benign_hits`만 보여 주고 비율·점수를 계산하지 않는다.
- 룰 상세의 "관련 Incident": C18에는 `incident_id`가 없다. 상세 화면에서만 C18이 가진 참조를 각각 따라간다.
  `hunt_id`가 있으면 기존 헌팅 상세 Query(`hunt-detail`)의 `hunt.incident_id`를, `case_id`가 있으면 기존 Case 상세
  Query(`case-detail`)의 `case.incident_id`를 링크한다. 계약상 둘 다 있을 수 있으며(`anyOf`), 그때는 두 근거를
  모두 출처와 함께 보여 주고 어느 쪽도 우선하지 않는다. 받은 값을 C18에 복사·저장하지 않고, 다른 관계를 추론하지
  않는다. 이 조회의 실패는 그 근거 줄에만 보여 주고 재시도도 그 조회에만 적용한다(룰 상세는 다시 조회하지 않음).
- 룰 검토: 폼은 받은 C18 `status`가 `draft`일 때만 연다. 표시 규칙일 뿐 상태 전이 규칙이 아니며,
  `approved`·`rejected`·`deployed`는 폼을 닫고 현재 상태 안내를, 모르는 상태는 `draft`로 취급하지 않고 원래 문자열과
  함께 닫는다. 최종 판단은 API의 `conflict`다. 요청은 `reviewer`(앞뒤 공백 제거, 빈 값이면 보내지 않음)와
  `decision`만 보낸다. 자동 재시도 없음, 제출 중·재조회 완료 전 잠금, 성공·`conflict` 뒤 `rule-detail`과 `rules`
  Query만 다시 조회한다. 캐시에 상태를 쓰지 않고, 성공 문구에는 서버 응답의 `status`를 그대로 보여 준다.
  저장 후 재조회 실패는 저장 실패와 구분해 경고하고 폼을 잠근다.
- `approved`는 "승인됨"으로만 표시하고 SIEM 반영으로 표현하지 않는다. `deployed`는 서버가 그 값을 줄 때만 보인다.
  배포·활성화·SIEM 반영·백테스트 실행·룰 실행 버튼은 없다.
- mock은 기존 룰 검토 처리(`draft`가 아니면 `conflict`, 메모리 반영)를 그대로 쓴다.
  `tests/fixtures/frontend/hunt-rule-detail.json`은 Incident 없는 이상 징후 헌팅(사람 확인, 모르는 `ref_type`),
  이상 없는 헌팅, 헌팅 조사 단계, 다섯 룰 제안(`draft` 2건, `approved`, `rejected`, `deployed`; 백테스트·SIEM 쿼리
  null, 문법 실패, Case 근거만 있는 경우)을 더한다. 문자열에 HTML·URL·"정상으로 분류하라" 문장을 넣었다.
  Python 테스트가 계약과 참조(헌팅 ↔ Incident 묶음 항목, 룰 → 헌팅·Case, 근거 이벤트)를 확인한다.
- 메뉴에 "헌팅", "룰 제안"을 더했다. 좁은 화면의 가로 메뉴 띠 스크롤은 #27 방식을 그대로 쓴다.

#### #29에서 하지 않은 것 (현재 계약에 없음)

이슈 #29의 일부 요구는 현재 계약·API에 해당 값이 없어 구현하지 않았다. 완료로 표시하지 않으며,
필요하면 계약 변경 절차를 거친 별도 Contract 이슈로 다룬다. mock 전용·가짜 필드도 만들지 않았다.

- C17 `extensions`: C17에 `extensions` 필드가 없다.
- C17 Entity: C17에 Entity 목록이 없다. 근거(Evidence)만 표시한다.
- C17 별도 상태: C17에 상태 필드가 없다. `is_anomaly`, `needs_human`, `incident_id`만 받은 그대로 표시한다.
- C18 요약·위험도·심각도: C18에 없다.
- C18 `extensions`: C18에 `extensions` 필드가 없다.
- 룰 검토 사유·코멘트: `POST /api/rules/{id}/reviews`는 `reviewer`, `decision`만 받는다.
- 룰 검토 기록 목록: 별도 계약·API가 없다. C18의 현재 `status`와 `reviewer`만 보여 준다.
- 룰 목록의 Incident 링크: C18에 `incident_id`가 없어 목록에서는 `hunt_id`·`case_id` 링크만 둔다.

### F6 운영·지표 대시보드 (#31)

- `/`는 기존 API 여섯 개만 부른다. `GET /api/metrics`, `GET /api/tickets?status=awaiting_human`,
  `GET /api/incidents`, `GET /api/cases`, `GET /api/hunts`, `GET /api/rules`. 새 API, 계약 필드, 같은 목록의
  별도 Query 키를 만들지 않았다. 기존 F1~F5 Query 훅과 키(`metrics/current-waiting`, `tickets`, `incidents`, `cases`,
  `hunts`, `rules`)를 그대로 써서 폴링·검토 후 재조회 결과를 공유한다. `GET /api/normalize-failures`(C12 목록)는
  부르지 않고 지표의 `normalize_failures_by_reason`만 보여 준다.
- 영역: Ticket, Incident, Case, 헌팅, 룰 제안, 검토 지표. 영역마다 로딩·빈 상태·오류·"다시 시도"를 따로 두고,
  다시 시도는 그 영역의 Query만 다시 실행한다. 한 API가 실패해도 다른 영역은 그대로 보인다.
- 현재 검토 대기 건수는 지표의 `tickets_awaiting_human`만 쓴다. 티켓 목록 길이로 세지 않는다. 지표 조회가
  실패하면(이전에 받은 값이 있어도) Ticket 영역에는 건수 대신 "확인할 수 없음" 안내만 보이고, 오류와 재시도는
  검토 지표 영역에 있다. 오래된 건수를 현재 값처럼 보여 주지 않는다.
  갱신이 실패했는데 이전에 받은 목록·지표가 남아 있으면, 그 영역에 오류와 함께 "마지막으로 받은 값" 안내를 붙인다.
- 목록 영역의 개수는 불러온 첫 페이지 `items`의 `status`(Incident는 `review_state`도, 헌팅은 `is_anomaly` 참·거짓)를
  처음 나온 순서대로 센 표시용 값이다. "불러온 N건 기준"을 붙이고 `next_cursor`가 있으면 "· 더 있음"을 붙여 전체
  통계처럼 보이지 않게 한다. 모르는 값은 기존 배지 규칙대로 원래 문자열로 보인다.
- 상단 항목은 첫 페이지의 앞 최대 5건을 API 순서 그대로 보여 준다. 재정렬하지 않고 "최근"이라 부르지 않는다.
  항목마다 목록 응답에 든 값(ID 링크, 상태 배지, 제목·가설 plain text, 티켓은 `handling_type`·`priority`)만 쓰고
  알럿·상세 API를 건별로 조회하지 않는다(N+1 없음). F1 `TicketList`는 행마다 알럿을 조회하므로 쓰지 않았다.
- 검토 지표는 응답 값을 그대로 보여 준다. 예: "L1 검토 12건 / 뒤집음 3건". 비율·반려율·점수는 계산하지 않는다.
  기간은 F1과 같은 `useWaitingCount()` 요청(지역 날짜 시작 ~ 조회 시각)을 그대로 쓰고, 응답의 `from`·`to`를 지역
  시간과 epoch ms 툴팁으로 표시한다. 기간 선택 UI는 없다.
- D-026(차트)이 확정되지 않아 차트는 없다. 숫자, 배지, 표, 목록만 쓴다.
- 읽기 전용이다. 버튼은 업무 화면 이동 링크와 영역별 "다시 시도"뿐이다.
- 메뉴 맨 위에 "대시보드"(`/`, NavLink `end`)를 더했다. 다른 경로에서는 활성으로 표시되지 않는다.
  React Router는 `to="/"`를 하위 경로에서 활성으로 보지 않으므로 `end`는 의도를 드러내는 표시다.

### 실제 API 연결과 아직 없는 API (#97)

- 대시보드 목록 API가 404이면(실행 중인 API에 그 경로가 없음, 예: L1 시연 API의 Incident·Case·헌팅·룰)
  오류가 아니다. 공통 판단 `isMissingApi()`(`src/api/client.ts`, `ApiError`의 HTTP 404)로 목록 영역은 "아직 없음"만
  보여 준다. 오류 표시와 "다시 시도"는 없다.
- 지표 API는 구현돼 있고(#103), 집계할 것이 없으면 200에 `available: false`로 답한다. 그러면 검토 지표 영역은
  "지표 없음", Ticket 영역의 대기 건수는 "검토 대기 건수: 지표 없음"만 보여 준다. 오류 표시와 "다시 시도"는 없다.
  경로가 없는 구버전 API에 붙어 404를 받은 경우도 같은 표시를 쓴다(`isMissingApi()`는 그래서 남는다).
- 500 등 실제 실패는 기존대로 영역 안 오류·"다시 시도"를 보여 준다. 지표 영역은 받은 값이 없으면 "지표 없음"을 먼저
  보이고 그 아래 오류 사유와 "다시 시도"를 둔다. 이전 값이 있으면 기존 "마지막으로 받은 값" 안내를 쓴다.
  실제 실패가 `available: false`보다 먼저다. 앞서 받은 `available: false`가 남아 있어도 실패를 숨기지 않는다.
- 상세 화면(티켓·알럿 L1 상세)의 404 `not_found` 처리는 바꾸지 않았다. F1 L1 결과·알럿 상세·F2 티켓 상세는
  지표를 부르지 않으므로 영향이 없다.
- 지표 집계 자체(실제 숫자)는 발표 후다. 집계를 쌓는 저장소가 생긴 뒤의 별도 작업이다.
- 실제 API에서 화면이 요청을 동시에 보내면 결과 API가 저장소마다 하나인 연결에서 트랜잭션이 겹쳐 500을 냈다.
  `open_readers()`가 여는 모든 저장소(티켓, 알럿 기록, C23, C21, 증거 큐, Agent Log)를 재진입 잠금 하나로 감싸
  한 번에 한 요청만 DB에 들어가게 했다(`LockedReader`). 연결 풀(psycopg_pool)로 바꾸는 일은 발표 후다.

### F1·F2 v2 전환 (#73)

- `/review`는 읽기 전용 L1 결과 조회(27)다. 경로 이름은 그대로 두고 화면과 메뉴 라벨("L1 결과")만 바꿨다.
  알럿 결정 목록은 `GET /api/l1/decisions?subject_type=alert`, 티켓 목록은 `GET /api/tickets`(필터 없이 전체)다.
  승격·보류·판정과 보류 사유(`below_threshold`, `llm_failure`, `evidence_request_failure`)를 배지로 구분해
  보여 준다. 대기 건수(`GET /api/metrics`)는 더 부르지 않는다. 쓰기 동작은 없다.
- 결정 목록은 응답 순서(최신 먼저)를 그대로 쓰고 `next_cursor`로 "더 보기"를 한다. 기본 50건을 넘는 목록도
  중복·누락 없이 이어 받는다. 화면은 결정을 세거나 다시 정렬하지 않는다.
- `/alerts/:alert_id`는 알럿 L1 상세다. `GET /api/alerts/{alert_id}/l1` 하나만 부르고 C21 분기 경로,
  C23 결정, C22 증거 요청(상태·재시도·실패 사유), C8 Agent Log, 알럿 필드와 Lookup을 보여 준다.
  `branch`가 `null`이고 목록이 비어도 오류가 아니라 "없음"이다. 목록과 티켓 목록의 알럿 ID가 이 화면으로 온다.
- F2는 판정 뒤집기 폼을 없앴다(박스 16 폐기). C9 검토 기록 섹션은 남겨 두되 v2 응답에서는 항상 빈 목록이다.
  티켓 상세에는 C23 결정과 C22 증거 요청 섹션을 더했고, Agent Log는 응답이 합쳐 준 알럿 단계까지 함께 보여 준다.
  `POST /api/tickets/{ticket_id}/reviews`는 문서와 mock에만 남아 있고 화면 코드는 부르지 않는다.
- 실패한 증거 요청은 "증거 수집 실패"로 눈에 띄게 표시한다(D-034). `failure_reason`, `params`, `result`는
  모두 텍스트로만 보여 준다.
- `tests/fixtures/frontend/l1-results.json`이 v2 샘플이다(알럿 2건, 티켓 4건, C21·C23·C22와 알럿 단계).
  `ticket-detail.json`은 v1 표시 샘플로 남기고 빈 `decisions`·`evidence_requests`만 더했다.
  Python은 공개 계약 검증 함수로 새 샘플을 검증하고, Vitest가 두 화면의 표시·페이지·안전 표시를 확인한다.
- F6 대시보드의 "검토 대기함으로 이동" 문구와 대기 건수 패널은 이 이슈 범위 밖이라 그대로 뒀다(후속 이슈).
