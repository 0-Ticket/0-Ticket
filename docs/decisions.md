# 결정 대장

아키텍처 문서의 데이터셋과 도구는 후보일 뿐이다. 여기서 "확정"된 것만 코드에 들어간다.

상태: `후보` → `검토중` → `확정` / `보류` / `폐기`

| ID | 항목 | 관련 박스 | 후보 | 상태 | 메모 |
|---|---|---|---|---|---|
| D-001 | 언어 · 패키지 관리 (백엔드) | 전체 | Python 3.12 + uv | 확정 | 린트 ruff, 테스트 pytest 포함 (CI와 같음). 웹 화면(`frontend/`)은 D-018 ~ D-026으로 따로 정한다 |
| D-002 | RDB | 5, 6, 7, 10, 12, 18, 20, 22, 24 | PostgreSQL | 확정 | v2: Alert, Event, Lookup, Incident, Incident Artifact, Ticket, Case 모두 RDB. Event(7)도 RDB (D-028 폐기). 정규화 결과는 원본 Alert·Event와 별도 테이블에 두고 FK로 연결한다. 원본은 불변이고 보관 기간은 설정 값(기본 무기한) |
| D-003 | Vector DB | 8, 10, 22 | Qdrant | 확정 | v2: VDB에는 Ticket, Case만 넣는다 |
| D-004 | 데이터셋 (웹) | 1, 2, 3 | AIT Log Data Set V2 | 확정 | 데모에 활용 |
| D-005 | 데이터셋 (클라우드) | 1, 13 | flaws.cloud / Invictus Sigma-AWS / BOTSv3 | 보류 | Cloud 소스는 보류. 구조는 확장 가능하게 둔다 |
| D-006 | SIEM | 3, 15 | Wazuh (초기 구현 대상) | 확정 | 한 번에 하나의 외부 SIEM에 연결한다(초기 Wazuh, 확장 ELK·Splunk). 연결 구조는 D-037 |
| D-007 | 정규화 스키마 | 4 | OCSF | 확정 | 교수님 강조 항목. 버전은 D-017 |
| D-008 | 에이전트 구현 방식 | 11, 13, 14, 19, 23 | LangGraph / Claude Agent SDK / 직접 구현 | 후보 | |
| D-009 | 기본 LLM 제공자 | 11, 13, 14, 19, 23, 24 | claude -p / API / 로컬 모델 | 후보 | 기본으로 함께 제공할 제공자를 정함. OpenAI 호환 제공자는 항상 포함하고, 다른 모델은 설정으로 바꿈(`docs/llm-policy.md`) |
| D-010 | 기본 임베딩 모델 | 8 | KURE-v1 / bge-m3 | 후보 | 다른 임베딩은 어댑터로 추가 가능 |
| D-011 | 상관 규칙 형식 | (17 폐기) | Sigma 2.0 상관 규칙 / SQL 직접 | 폐기 | v2에서 Correlation(17)이 없어짐. Incident 묶음은 25 엔티티 분기 규칙이 맡는다 |
| D-012 | 티켓 · 케이스 관리 | 10, 22 | 자체 테이블 | 확정 | 티켓·케이스는 내부 저장소와 내부 UI로 관리한다. 외부 도구 동기화는 `case_systems` 플러그인으로 추가 |
| D-013 | 사람 검토 화면 | 21, 27 | 웹 | 확정 | 기본 검토 채널은 웹 화면(`frontend/`)과 화면용 API(`src/soc/api/`). 메신저 등 다른 채널은 `review_channels` 플러그인으로 추가 (`docs/frontend.md`) |
| D-014 | 데이터 계약 코드 형식 | 전체 | JSON Schema | 확정 | `docs/data-contracts.md`의 계약을 JSON Schema로 옮겨 단일 계약 원본으로 사용한다. 동일한 Schema에서 Python Pydantic 모델과 TypeScript 타입을 생성한다. Python에서는 원본 Schema의 조건 검증과 생성된 Pydantic 모델의 필드 검증을 함께 사용한다. 생성된 타입은 직접 수정하지 않는다. 런타임 검증과 LLM 출력 검증은 원본 Schema 검증 후 생성 Pydantic 모델로 변환하는 검증 함수 한 경로로 한다. 생성 모델만으로는 객체 수준 조건을 검증하지 못한다. jsonschema는 런타임 의존성이다. |
| D-015 | 설정 파일 형식 | 전체 | TOML / YAML | 후보 | TOML은 표준 라이브러리(`tomllib`)로 읽을 수 있어 의존성이 없음 (`docs/extensibility.md` 4항) |
| D-016 | 오픈소스 라이선스 | 전체 | Apache-2.0 / MIT / AGPL-3.0 | 후보 | 기업 커스텀·사내 플러그인 허용 범위에 영향. 데이터셋 라이선스(예: CC BY-NC-SA)와는 별개 |
| D-017 | OCSF 버전 | 4 | 1.9.0 (2026-08 최신 정식) / 그 이전 1.x | 확정 | 도구·라이브러리 지원 범위와 함께 검토 |
| D-018 | 웹 화면 프레임워크 · 빌드 | 화면 | Vite + React + TypeScript (SPA) | 확정 | 내부 도구라 서버 렌더링과 SEO는 필요 없음. Vite 기반 React + TypeScript SPA로 구성한다 |
| D-019 | UI 구성 | 화면 | Tailwind CSS + shadcn/ui | 확정 | 내부 SOC 화면의 테이블·폼·다이얼로그·배지 등 반복 UI를 구성한다. 컴포넌트 코드는 프로젝트 내부에서 관리하며 라이트·다크 모드를 지원한다 |
| D-020 | 서버 데이터 관리 | 화면 | TanStack Query | 확정 | API 조회, 캐시, 재조회, 폴링, mutation 이후 invalidation을 담당한다. 화면 컴포넌트에서 서버 상태 관리 로직을 직접 구현하지 않는다 |
| D-021 | 화면 라우팅 | 화면 | React Router | 확정 | Vite 기반 SPA의 클라이언트 라우팅. 경로 목록은 `docs/frontend.md` "화면 목록"이 기준이다 |
| D-022 | Mock API | 화면 | MSW | 확정 | 백엔드 없이 `docs/api-contracts.md`에 정의된 HTTP 경로와 응답 구조를 그대로 모킹한다. 화면 코드는 mock 여부를 알지 못하며 환경변수 하나로 실제 API와 전환한다 |
| D-023 | 화면 테스트 | 화면 | Vitest + Testing Library | 확정 | 컴포넌트, 사용자 동작, 계약 기반 렌더링, 보안 표시 규칙을 테스트한다. Playwright는 E2E 테스트가 필요한 단계에서 별도 도입한다 |
| D-024 | Node 버전 · 패키지 관리 | 화면 | Node LTS + pnpm | 확정 | Node LTS를 기준으로 사용하고 `pnpm-lock.yaml`을 커밋해 로컬과 CI의 의존성을 동일하게 유지한다. 정확한 Node 메이저 버전은 F0에서 `frontend/.nvmrc`와 `package.json`의 `engines`, pnpm 버전은 `packageManager`로 고정한다 |
| D-025 | 계약 타입 공유 방식 | 화면, 전체 | JSON Schema에서 Python·TypeScript 타입 생성 | 확정 | 계약의 단일 원본은 JSON Schema다. Python Pydantic 모델과 `frontend/src/contracts/generated/`의 TypeScript 타입을 동일한 Schema에서 생성해 프론트·백엔드 계약 불일치를 방지한다. 생성된 타입 파일은 직접 수정하지 않는다 |
| D-026 | 차트 | 화면 | Recharts / 다른 차트 라이브러리 | 후보 | 지표 대시보드(F6) 전에 정함 |
| D-027 | 화면용 API 서버 | 화면, 전체 | FastAPI / 다른 Python 웹 프레임워크 | 후보 | `src/soc/api/`. 화면을 실제 백엔드에 붙이기 전에 정함. 그전까지 화면은 mock(D-022)을 씀 |
| D-028 | 이벤트 저장소 | 7, 23 | OpenSearch | 폐기 | 이 프로젝트의 자체 저장소로 OpenSearch를 쓰지 않는다. Event는 RDB(D-002). 외부 SIEM(ELK 등)이 내부적으로 쓰는 저장소와는 무관하다 |
| D-029 | OCSF 구현 라이브러리 | 4 | 직접 구현 | 확정 |  |
| D-030 | 화면 린트 · 포맷 | 화면 | ESLint + Prettier | 확정 | 린트는 ESLint, 포맷은 Prettier. CI에서는 포맷을 고치지 않고 검사만 한다 |
| D-031 | 계약 코드 생성 도구 | 전체, 화면 | datamodel-code-generator (Python Pydantic) + json-schema-to-typescript (TypeScript) | 확정 | D-014·D-025의 생성 도구. 생성 명령은 하나로 묶고, CI에서 다시 생성했을 때 차이가 없는지 검사한다 |
| D-032 | 계약 Schema 위치 · 버전 | 전체 | 레포 루트 `contracts/`, JSON Schema draft-07 | 확정 | Python과 화면이 함께 쓰므로 어느 한쪽 폴더에 두지 않는다. draft-07은 두 생성 도구가 모두 지원한다 |
| D-033 | 알림 채널 | 사용자 접점, 21 | Slack | 확정 | 티켓은 내부 UI, 알림은 Slack. 트리거는 "L2 분석이 끝나 사람 승인이 필요할 때"뿐이다. L1 단계 이벤트는 알리지 않는다. 렌더링 금지는 D-040 |
| D-034 | 증거 요청 큐 구현 | 26 | PostgreSQL 테이블 큐 | 확정 | 실패하면 재시도 N회(설정 값) 후 실패 상태로 두고, 해당 L1 Ticket은 보류한다. 실패는 27에 표시한다. L2 요청 실패의 처리는 정하지 않았다 |
| D-035 | SIEM MCP | 15 | 선택된 SIEM용 SIEM MCP 어댑터 (초기 Wazuh) | 확정 | 읽기 전용 도구만 제공한다. 코어와 에이전트는 SIEM과 무관하게 같은 인터페이스로 부른다. 확장 ELK·Splunk. 전체 구조는 D-037 |
| D-036 | L1 판정 결과 조건 | 11 | 확신도 임계값 (설정 값, 초기 0.8) | 확정 | 엔티티 조회: 이상 → 승격, 미만 → 보류. Ticket 판정: 오탐 + 이상 → 종결, 이상 행위 + 이상 → L2 승격, 미만 → 보류. "이상 행위 · 종결" 경로는 없다. 보류는 출처와 무관하게 모두 L3 헌팅 데이터 풀로 간다. LLM 실패(형식 오류, 근거 ID 오류, 예산 초과)는 보류. 사람에게 넘기지 않는다. 임계값은 AIT 데이터셋 평가 후 조정 |
| D-037 | SIEM 연결 구조 | 3, 4, 15 | 외부 SIEM 1개 + SIEM 커넥터 + SIEM MCP 어댑터 | 확정 | SIEM은 이 프로젝트 밖(또는 로컬)에 이미 구축되어 있다고 가정하고 연결만 한다. 한 번에 하나만 연결하고 설정으로 고른다. 여러 SIEM 동시 연결과 로그 종류별 라우팅은 범위 밖. 초기 Wazuh, 확장 ELK·Splunk는 어댑터 추가와 설정 변경만으로. SIEM별 차이는 커넥터와 정규화 규칙의 입력단에서 흡수한다(OCSF 정규화는 D-017, D-029 그대로) |
| D-038 | Ticket 출처 구분 | 10, 11, 23, 25 | 세 값: L1 승격 티켓 / L3 승격 티켓 / 시나리오 티켓 | 확정 | L1 승격·시나리오 티켓은 증거 요청 큐 → 전문가 + MCP → L1 판정, L3 승격 티켓은 L2 Ticket으로 바로 들어간다. 필드 이름과 값은 계약 이슈에서 정한다(제안: `origin` = `l1_escalated` / `l3_escalated` / `scenario`) |
| D-039 | L2 재실행 기준 | 18, 19, 21 | 새 엔티티·새 증거 ID가 늘 때만 재실행, 최대 횟수 설정 (초기 5) | 확정 | 발견한 정보는 한도 없이 항상 Incident에 붙인다. 최대 재실행에 걸려도 정보는 붙이고 자동 재실행만 멈추며 표시를 남긴다. 반려 흐름(#21)은 유지: 반려 사유로 재분석, 2회 반려면 사람 처리 |
| D-040 | 알림 렌더링 금지 | 사용자 접점 | 텍스트로만 표시 | 확정 | Slack 알림에도 HTML·마크다운 렌더링 금지를 적용한다(`docs/security-policy.md` 7항) |

## 결정 기록

확정할 때마다 아래에 한 줄씩 남긴다.

- 2026-10-10 · D-001 확정: Python 3.12 + uv. 린트는 ruff, 테스트는 pytest.
- 2026-10-10 · D-002 확정: PostgreSQL.
- 2026-10-10 · D-007 확정: 정규화 스키마는 OCSF. 버전은 D-017에서 따로 정한다.
- 2026-10-13 · D-013 확정: 사람 검토 화면은 웹. 다른 채널은 검토 채널 플러그인으로 추가한다.
- 2026-10-13 · D-014 확정: 데이터 계약의 단일 원본은 JSON Schema로 한다. 동일한 Schema에서 Python Pydantic 모델과 TypeScript 타입을 생성하고, Python에서는 원본 Schema의 조건 검증과 생성된 Pydantic 모델의 필드 검증을 함께 사용한다.
- 2026-10-13 · D-018 확정: 웹 화면은 Vite + React + TypeScript 기반 SPA로 구성한다. 내부 SOC 도구이므로 서버 사이드 렌더링과 SEO는 사용하지 않는다.
- 2026-10-13 · D-019 확정: UI는 Tailwind CSS + shadcn/ui로 구성한다. 내부 SOC 화면에 필요한 반복 UI를 프로젝트 내부 컴포넌트로 관리하고 라이트·다크 모드를 지원한다.
- 2026-10-13 · D-020 확정: 서버 데이터 관리는 TanStack Query를 사용한다. API 조회, 캐시, 폴링, 재조회와 mutation 이후 데이터 갱신을 담당한다.
- 2026-10-13 · D-021 확정: 화면 라우팅은 React Router를 사용한다. Vite 기반 SPA의 문서 정의 경로를 클라이언트 라우팅으로 구성한다.
- 2026-10-13 · D-022 확정: Mock API는 MSW를 사용한다. 실제 API와 동일한 HTTP 경로와 응답 구조를 사용하며 환경변수 하나로 실제 API와 전환한다.
- 2026-10-13 · D-023 확정: 화면 테스트는 Vitest + Testing Library를 사용한다. Playwright는 E2E 테스트가 필요한 단계에서 추가한다.
- 2026-10-13 · D-024 확정: 프론트엔드는 Node LTS + pnpm을 사용한다. `pnpm-lock.yaml`을 커밋하여 개발 환경과 CI의 의존성을 일치시킨다.
- 2026-10-13 · D-025 확정: 계약 타입은 JSON Schema를 기준으로 Python과 TypeScript 양쪽에 생성한다. 생성된 타입 파일은 직접 수정하지 않는다.
- 2026-10-13 · D-030 확정: 화면 린트는 ESLint, 포맷은 Prettier.
- 2026-10-13 · D-031 확정: 계약 코드 생성은 Python은 datamodel-code-generator(Pydantic), TypeScript는 json-schema-to-typescript.
- 2026-10-13 · D-032 확정: 계약 Schema는 레포 루트 `contracts/`에 JSON Schema draft-07로 둔다.
- 2026-10-13 · D-014 보완: 런타임 검증 경로
- 2026-10-15 · D-003 확정: Vector DB는 Qdrant. 다른 벡터 DB는 어댑터로 추가한다.
- 2026-10-15 · D-004 확정: 웹 데이터셋은 AIT Log Data Set V2. 첫 데모에 사용한다.
- 2026-10-15 · D-006 확정: SIEM은 Wazuh 기준으로 먼저 개발한다. 다른 SIEM은 어댑터로 추가한다.
- 2026-10-15 · D-017 확정: OCSF 1.9.0.
- 2026-10-15 · D-028 확정: 이벤트 저장소는 OpenSearch.
- 2026-10-15 · D-029 확정: OCSF 정규화는 라이브러리 없이 직접 구현한다. Wazuh 버전과 무관하게 동작하게 한다.
- 2026-10-18 · 아키텍처 v2 반영 (#33): D-005 보류(Cloud 보류). D-011 폐기(Correlation 없어짐). D-012 확정: 티켓·케이스는 자체 테이블과 내부 UI. D-028 폐기: OpenSearch를 쓰지 않고 Event도 RDB. D-033 확정: 알림은 Slack. D-034, D-035, D-036 후보 추가.
- 2026-10-18 · D-036 갱신: 확신도 높음 → 종결, 낮음 → 보류. 임계값, 오탐(보류)의 L3 전달 여부, 이상 행위 종결·L2 승격 조건은 미정. D-033에 트리거 이벤트 미정을 명시.
- 2026-10-18 · 결정 반영 (#33): D-033 트리거 확정(L2 승인 필요 시만). D-034 확정: PostgreSQL 테이블 큐, N회 재시도 후 실패·Ticket 보류. D-035 확정: 선택된 SIEM용 SIEM MCP 어댑터. D-036 확정: 확신도 임계값 0.8(설정 값). D-037 SIEM 연결 구조, D-038 Ticket 출처 구분, D-039 L2 재실행 기준, D-040 알림 렌더링 금지 확정. D-002에 정규화 결과 별도 테이블·원본 불변·보관 기간 반영. D-006·D-028 메모 정리.
