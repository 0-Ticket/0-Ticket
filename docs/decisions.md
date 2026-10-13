# 결정 대장

아키텍처 문서의 데이터셋과 도구는 후보일 뿐이다. 여기서 "확정"된 것만 코드에 들어간다.

상태: `후보` → `검토중` → `확정` / `보류`

| ID | 항목 | 관련 박스 | 후보 | 상태 | 메모 |
|---|---|---|---|---|---|
| D-001 | 언어 · 패키지 관리 (백엔드) | 전체 | Python 3.12 + uv | 확정 | 린트 ruff, 테스트 pytest 포함 (CI와 같음). 웹 화면(`frontend/`)은 D-018 ~ D-026으로 따로 정한다 |
| D-002 | RDB | 5, 6, 10, 12, 18, 20, 22, 24 | PostgreSQL | 확정 | Event(7)는 D-028 |
| D-003 | Vector DB | 8 | pgvector / Qdrant | 후보 | 기본 구현체를 정함. 다른 벡터 DB는 어댑터로 추가 가능. D-002가 PostgreSQL이면 pgvector가 단순 |
| D-004 | 데이터셋 (웹) | 1, 2, 3 | AIT-LDS V2 / AIT-ADS | 후보 | ADS는 SIEM 알럿이 이미 있음 |
| D-005 | 데이터셋 (클라우드) | 1, 13 | flaws.cloud / Invictus Sigma-AWS / BOTSv3 | 후보 | |
| D-006 | SIEM | 3 | Splunk | 후보 | 기존에 사용하던 SIEM을 연결 가능한 구조로, 기존 사용하던 SIEM이 없는 경우 Splunk 자동 구축 |
| D-007 | 정규화 스키마 | 4 | OCSF | 확정 | 교수님 강조 항목. 버전은 D-017 |
| D-008 | 에이전트 구현 방식 | 9, 11, 19, 23 | LangGraph / Claude Agent SDK / 직접 구현 | 후보 | |
| D-009 | 기본 LLM 제공자 | 9, 11, 13, 14, 19, 23, 24 | claude -p / API / 로컬 모델 | 후보 | 기본으로 함께 제공할 제공자를 정함. OpenAI 호환 제공자는 항상 포함하고, 다른 모델은 설정으로 바꿈(`docs/llm-policy.md`) |
| D-010 | 기본 임베딩 모델 | 8 | KURE-v1 / bge-m3 | 후보 | 다른 임베딩은 어댑터로 추가 가능 |
| D-011 | 상관 규칙 형식 | 17 | Sigma 2.0 상관 규칙 / SQL 직접 | 후보 | 아키텍처 원본(2026-10-13)은 Sigma Rule을 적어 둠 |
| D-012 | 티켓 · 케이스 관리 | 10, 22 | 자체 테이블 / TheHive / DFIR-IRIS | 후보 | |
| D-013 | 사람 검토 화면 | 16, 21 | 웹 | 확정 | 기본 검토 채널은 웹 화면(`frontend/`)과 화면용 API(`src/soc/api/`). 메신저 등 다른 채널은 `review_channels` 플러그인으로 추가 (`docs/frontend.md`) |
| D-014 | 데이터 계약 코드 형식 | 전체 | pydantic / dataclass / JSON Schema | 후보 | `docs/data-contracts.md`를 코드로 옮기는 방식. 구현 순서 0단계 전에 정함. LLM 출력 검증에도 쓰므로 검증 기능이 있는 쪽이 유리 |
| D-015 | 설정 파일 형식 | 전체 | TOML / YAML | 후보 | TOML은 표준 라이브러리(`tomllib`)로 읽을 수 있어 의존성이 없음 (`docs/extensibility.md` 4항) |
| D-016 | 오픈소스 라이선스 | 전체 | Apache-2.0 / MIT / AGPL-3.0 | 후보 | 기업 커스텀·사내 플러그인 허용 범위에 영향. 데이터셋 라이선스(예: CC BY-NC-SA)와는 별개 |
| D-017 | OCSF 버전 | 4 | 1.9.0 (2026-08 최신 정식) / 그 이전 1.x | 후보 | 도구·라이브러리 지원 범위와 함께 검토 |
| D-018 | 웹 화면 프레임워크 · 빌드 | 화면 | Vite + React + TypeScript (SPA) / Next.js | 후보 | 내부 도구라 서버 렌더링과 SEO는 필요 없음. 화면 트랙 F0 전에 정함 |
| D-019 | UI 구성 | 화면 | Tailwind CSS + shadcn/ui / 다른 컴포넌트 라이브러리 | 후보 | F0 전에 정함 |
| D-020 | 서버 데이터 관리 | 화면 | TanStack Query / 직접 fetch | 후보 | 폴링, 캐시, 재조회. F0 전에 정함 |
| D-021 | 화면 라우팅 | 화면 | React Router / TanStack Router | 후보 | D-018이 Next.js면 필요 없음. F0 전에 정함 |
| D-022 | Mock API | 화면 | MSW / 정적 JSON | 후보 | 백엔드 없이 `docs/api-contracts.md`의 API를 흉내 냄. F0 전에 정함 |
| D-023 | 화면 테스트 | 화면 | Vitest + Testing Library (+ 나중에 Playwright) | 후보 | F0 전에 정함 |
| D-024 | Node 버전 · 패키지 관리 | 화면 | Node LTS + pnpm / npm | 후보 | 잠금 파일(lock)을 커밋해 CI와 같은 버전을 씀. F0 전에 정함 |
| D-025 | 계약 타입 공유 방식 | 화면, 전체 | 손으로 작성 후 생성으로 전환 / 처음부터 JSON Schema로 생성 | 후보 | 추천: 지금은 `frontend/src/contracts/`에 손으로 쓰고, D-014가 정해져 계약 코드에서 JSON Schema를 뽑을 수 있게 되면 생성으로 바꿈 |
| D-026 | 차트 | 화면 | Recharts / 다른 차트 라이브러리 | 후보 | 지표 대시보드(F6) 전에 정함 |
| D-027 | 화면용 API 서버 | 화면, 전체 | FastAPI / 다른 Python 웹 프레임워크 | 후보 | `src/soc/api/`. 화면을 실제 백엔드에 붙이기 전에 정함. 그전까지 화면은 mock(D-022)을 씀 |
| D-028 | 이벤트 저장소 | 7, 23 | OpenSearch / PostgreSQL | 후보 | 아키텍처 원본(2026-10-13)은 OpenSearch. Event는 양이 많고 L3가 기준선 조회를 많이 함. 다른 로그 저장소는 `stores` 어댑터로 추가 |
| D-029 | OCSF 구현 라이브러리 | 4 | ocsf-lib-py / 직접 구현 | 후보 | 아키텍처 원본(2026-10-13)은 ocsf-lib-py. D-017(OCSF 버전) 지원 범위와 함께 검토 |

## 결정 기록

확정할 때마다 아래에 한 줄씩 남긴다.

- 2026-10-10 · D-001 확정: Python 3.12 + uv. 린트는 ruff, 테스트는 pytest.
- 2026-10-10 · D-002 확정: PostgreSQL.
- 2026-10-10 · D-007 확정: 정규화 스키마는 OCSF. 버전은 D-017에서 따로 정한다.
- 2026-10-13 · D-013 확정: 사람 검토 화면은 웹. 다른 채널은 검토 채널 플러그인으로 추가한다.