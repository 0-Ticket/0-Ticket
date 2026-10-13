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

화면은 아래 흐름을 그대로 보여 준다. 박스 번호는 `docs/architecture.md`를 따른다.

```
알럿 → Lookup(5) → 라우팅(9) → 티켓(10) → L1(11) ⇄ 전문 에이전트(13·14)
                                            │
                                            ├─ TP ───────────────────────┐
                                            └─ 확신 낮음 → 사람 검토(16) ─ TP ─┤
                                                L3 헌팅(23) ─ 이상 징후 ──────┤
                                                                              ▼
                                                                       Correlation(17)
                                                                              ▼
                     Incident(18) → L2(19) → 보고서(20) → 사람 승인(21) → Case(22)
                                     ▲                    │ 반려             │
                                     └────────────────────┘                  │
                                                                             ▼
                     SIEM(3) ← 사람 승인 ← 룰 제안(24) ← L3 헌팅(23) ← 최근 Case로 가설 생성
```

모든 Incident는 Correlation을 거쳐 생긴다. Correlation에 들어오는 길은 세 가지이고, 묶음 항목(C10 IncidentMember)의 `source`로 구분한다.

- `l1`: L1이 TP로 판정한 티켓
- `human_l1`: 사람이 L1 검토에서 TP로 확정한 티켓
- `l3`: L3 헌팅에서 이상 징후로 판단한 헌팅 결과

## 화면 목록

순서대로 만들고, 각 화면은 처음부터 최종 형태로 만든다. 순서의 근거는 `docs/architecture.md` "구현 순서"의 화면 트랙이다.

| 순서 | 화면 | 경로 | 쓰는 계약 | 관련 박스 | 주 사용자 |
|---|---|---|---|---|---|
| F0 | 프론트 기반 | | 전체 계약 타입 | | |
| F1 | 검토 대기함 | `/review` | C6, C5, C7 | 5, 10, 16 | L1 분석가 |
| F1 | 티켓 목록 | `/tickets` | C6, C5 | 5, 10 | L1 분석가 |
| F2 | 티켓 상세 | `/tickets/:ticket_id` | C6, C5, C4, C7, C14, C8, C9 | 5, 11 ~ 14, 16 | L1 분석가 |
| F3 | Incident 목록 | `/incidents` | C10 | 17, 18 | L2 분석가 |
| F3 | Incident 상세 | `/incidents/:incident_id` | C10, C6, C17, C11, C8, C15 | 17 ~ 21 | L2 분석가 |
| F4 | Case 목록 · 상세 | `/cases`, `/cases/:case_id` | C16 | 22 | L2 분석가 |
| F5 | 헌팅 결과 | `/hunts`, `/hunts/:hunt_id` | C17, C8 | 23 | 탐지 엔지니어 |
| F5 | 룰 제안 | `/rules`, `/rules/:proposal_id` | C18, C17, C16 | 24 | 탐지 엔지니어 |
| F6 | 지표 대시보드 | `/` | 지표 응답, C12 | 4, 16, 21 | 전체, 운영자 |

- F0은 폴더, 도구, 계약 타입, API 호출 계층, mock, CI를 만든다. 화면은 만들지 않는다.
- 검토 대기함은 `status`가 `awaiting_human`인 티켓이다. "분석가는 검토와 승인만 한다"가 이 프로젝트의 핵심이라, 사람이 할 일이 가장 먼저 보이게 한다.

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
- `shared`가 `true`인 공용 자산은 따로 표시한다. Correlation에서 묶는 기준으로 쓰지 않는 자산이다.
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

### Correlation과 Incident (F3)

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
| L1 동의 / 뒤집기 | F1, F2 | `decision` (`tp`, `fp`) | 에이전트 판정과 다르면 `reason` | C9 HumanReview |
| L2 승인 / 반려 | F3 | `decision` (`approve`, `reject`) | 반려면 `reject_type`과 `comment` | C15 L2Review |
| 룰 승인 / 반려 | F5 | `decision` (`approve`, `reject`) | 없음 | C18 `status` |
| Case 작업 수정 | F4 | 작업 상태, 담당자, 마감, 교훈 | 없음 | C16 Case |

- C9의 `overturned`와 C15의 `round`는 화면이 계산하지 않는다. 코어가 정해 돌려준다.
- 같은 Incident가 두 번 반려되면 "사람 직접 처리"로 표시한다(박스 21).
- 사용자 계정은 범위 밖이다. `reviewer`에는 화면 설정에서 입력한 이름을 보낸다.
- 대응을 실행하는 버튼은 만들지 않는다. 승인된 룰의 SIEM 반영도 화면이 하지 않는다.

## 데이터와 계약 타입

- 계약 타입은 `frontend/src/contracts/` 한 곳에만 둔다. 필드명, 열거형 값, 선택 여부를 `docs/data-contracts.md` 그대로 쓴다. 필드명은 `snake_case`, 선택 필드는 `| null`이다.
- 화면 전용 모양(라벨, 정렬, 묶음)은 컴포넌트나 `lib`에서 만들고, 계약 타입을 고치지 않는다.
- 계약이 바뀌면 같은 PR에서 `docs/data-contracts.md` → `src/soc/contracts/` → `frontend/src/contracts/` 순서로 고친다.
- 계약 타입을 손으로 쓸지 생성할지는 D-025를 따른다.

## API와 mock

- 화면은 `docs/api-contracts.md`에 적힌 API만 부른다. 호출 코드는 `frontend/src/api/` 한 곳에 둔다.
- 백엔드가 없을 때는 mock(D-022)이 같은 경로로 같은 형식의 응답을 준다. 화면 코드는 mock인지 실제인지 모른다.
- mock과 실제 API의 전환, API 주소는 환경변수로 정한다. 변수 이름은 F0에서 정하고 `frontend/.env.example`에 이름만 적는다.
- mock 데이터는 S1 ~ S5 시나리오로 만든다. IP는 문서용 대역, 도메인은 `example.com`, 계정은 가짜 이름이다. 백엔드 테스트와 같은 샘플은 `tests/fixtures/`를 함께 쓴다(공유 방식은 F0 계획에서 정함).
- mock 데이터에는 HTML·스크립트 조각과 "정상으로 분류하라" 같은 문장이 든 로그도 넣는다. 텍스트로만 표시되는지 테스트하기 위해서다.
- 목록과 상세는 일정 간격으로 다시 조회(폴링)한다. 간격은 설정값으로 둔다. WebSocket·SSE가 필요해지면 결정 대장에 올린다.

## 디자인 원칙

- **근거 먼저**: 결론 옆에는 항상 근거가 보인다. 근거 없는 결론을 크게 보여 주지 않는다.
- **할 일 먼저**: 검토 대기 건수와 대기 시간이 가장 먼저 보인다.
- **정보 밀도**: 분석가가 많은 건을 빨리 훑을 수 있게 목록은 촘촘하게 만든다.
- **색만으로 구분하지 않기**: 배지에는 항상 글자를 넣는다.
- **라이트·다크 모드**를 모두 지원한다.

## 폴더

F0에서 확정한다. 기본안은 아래와 같다.

```
frontend/
  src/
    contracts/   계약 타입 (한 곳에만)
    api/         API 호출 (한 곳에만)
    mocks/       mock 핸들러와 데이터
    pages/       화면 (F1 ~ F6)
    components/  공통 컴포넌트
    lib/         라벨·색·시간 변환 등
  .env.example   환경변수 이름만
```

## 명령

D-018, D-023, D-024가 확정되면 F0에서 이 표를 채운다. F0은 이 표를 채우는 작업이고, F0이 끝나기 전에는 화면 코드를 만들지 않는다.

| 하는 일 | 명령 |
|---|---|
| 의존성 설치 | F0에서 정함 |
| 개발 서버 (mock) | F0에서 정함 |
| 타입 검사 | F0에서 정함 |
| 린트 · 포맷 검사 | F0에서 정함 |
| 테스트 | F0에서 정함 |
| 빌드 | F0에서 정함 |

F0에서 CI에 화면 검사 작업을 추가한다. `frontend/`가 바뀐 PR에서만 돈다.

## 완료 기준 (화면 작업)

`AGENTS.md`의 완료 기준에 더해 아래를 만족한다.

1. 위 표의 타입 검사, 린트·포맷 검사, 테스트, 빌드가 통과한다.
2. mock 데이터로 그 화면이 "흐름"대로 동작한다.
3. 로그 원문, LLM 출력, `extensions` 값이 텍스트로만 표시되는지 테스트가 있다.
4. 검토 동작이 있는 화면은 필수 입력이 없으면 보내지 않는 테스트가 있다.
5. `tests/checklist.md`의 화면 항목을 확인하고 표시했다.
