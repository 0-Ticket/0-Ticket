# 데모 범위 (2026-11-03)

2일 데모까지 만들 범위다. 이 범위 밖은 데모 뒤에 한다. 구조는 `docs/architecture.md` v3(그림과 "박스 그룹과 코드 위치" 표), 계약은 `docs/data-contracts.md`, 결정은 `docs/decisions.md`가 기준이다. 실행 순서는 `docs/demo-run.md`(#183에서 만들고 각 이슈가 채운다)에 둔다. 중간 발표 범위는 `docs/milestone-l1.md`였다.

## 목표와 시연 흐름

**목표**: attack-to-alert 랩 ELK에서 가져온 알럿으로 수집부터 L1 판정, L2 분류·분석·승인과 Case, L3 수동 헌팅과 L2 재진입까지 공통 에이전트 하나로 시연한다.

```
ELK (attack-to-alert 랩, 외부 SIEM)
  → 수집 · 정규화 · 분기 (코드, 연속 실행)
       Alert·Event (RDB, 원본) → OCSF 정규화 → Lookup → 중복 Alert 제거 → 시나리오 분기
       ├─ 승격 대상 시나리오 → 시나리오 Ticket
       └─ 그 외 시나리오     → L1 승격 판단 → L1 승격 Ticket / 보류
  → L1 티켓 판정 → 오탐 종결 / 보류 / 이상 행위: Ticket을 L2 상태로
  → L2 Incident 분류 (새 Incident / 기존 Incident 추가)
  → L2 분석 (타임라인·ATT&CK, 영향 범위·원인, 탐지 룰·대응 방안) → Incident Artifact
  → Human 승인 (웹 화면) → Case (RDB + Qdrant)
  → L3 수동 헌팅 (보안 뉴스 + Case + Alert·Event) → 가설 기각 / 위협 존재
  → 위협 존재: L3 승격 Ticket을 L2 상태로 기록 → L2 재진입
```

- 수집부터 Ticket 원장까지는 코드가 한다. "판정 필요" 단계(L1 승격 판단·티켓 판정, L2 분류·분석, L3 헌팅)만 공통 에이전트 하나가 L1·L2·L3 스레드로 처리한다(D-008).
- 모델은 Groq `openai/gpt-oss-120b`이고 팀원별 키를 쓴다. 데모에서는 랩 데이터만 보낸다(D-009).
- L1 보류는 L1의 끝 상태다(D-036). L3 입력은 Alert·Event(RDB), Case, 보안 뉴스이고(D-045), SIEM MCP로 원본 로그를 확인할 수 있다.
- L3는 수동 명령으로 실행한다(D-046).

## 범위

| 구분 | 항목 | 박스 | 이슈 |
|---|---|---|---|
| 포함 | 결정 대장과 하네스 문서 | 문서 | #182 |
| | ELK 수집 → 정규화 → 분기 연속 실행, 데이터셋 재생(`direct`) 삭제 | 3, 4, 5, 6, 7, 25 | #183 |
| | OCSF 정규화 바로잡기(정규화 전·후 계약 분리, OCSF 원형 저장) | 4 | #189 |
| | 공통 에이전트 코어(OpenAI Agents SDK, 프롬프트 오버라이딩, 스레드 실행기, `fake` 백엔드), 에이전트 도구 위치 이동(`src/soc/mcp/`) | 28, 12, 15 | #184 |
| | L1 승격 판단·티켓 판정을 공통 에이전트로 전환, 판정 끝난 Ticket의 Qdrant 저장 유지 | 10, 11, 27 | #185 |
| | L2 입구, Incident 분류, Human 승인 화면 연결, Case 저장(RDB + Qdrant) | 18, 19, 21, 22 | #186 |
| | L2 분석(Incident Artifact, 탐지 룰·대응 방안 제안) | 19, 20, 24 | #187 |
| | SSH MCP | 15 | #187 |
| | 보안 뉴스 수집, L3 수동 헌팅, 헌팅 기록 화면 조회 | 23, 29 | #188 |
| 제외 | Slack 알림 (결정 D-033은 유지) | 사용자 접점 | |
| | Wazuh·Cloud (Wazuh는 이후 확장 D-006, Cloud는 보류 D-005) | 3, 15 | |
| | 로그인·SIEM 설정 화면 | 사용자 접점 | #173, #138 |
| | 매핑 프로필 | 3, 4 | #136 |
| | 대응 실행 | | |
| | 탐지 룰 자동 배포 | 24 | |
| | 화면에서 헌팅을 시키는 기능 (D-046) | 23 | |

## 이슈별 담당과 순서

#182는 다른 이슈가 계획의 근거로 쓰므로 가장 먼저 머지한다. "선행"은 각 이슈 본문의 순서 조건이다.

| 이슈 | 담당 | 내용 | 선행 | 마이그레이션 |
|---|---|---|---|---|
| #182 | Pandyo | 결정 대장과 하네스 문서 | 없음 | 없음 |
| #183 | uptime-zero | 데이터셋 재생 삭제, 수집 파이프라인 연속 실행(`python -m soc.pipeline`) | 없음 | 없음 |
| #184 | Pandyo | 공통 에이전트 코어(`python -m soc.agent`), MCP 코드를 `src/soc/mcp/`로 이동(첫 커밋), 첫날 안에 `fake` 백엔드까지 머지 | 없음 | 없음 |
| #189 | uptime-zero | OCSF 정규화 바로잡기 | 병렬 진행, PR과 머지는 #183 뒤 | `0095`~`0099` |
| #185 | uptime-zero | L1 승격 판단·티켓 판정을 공통 에이전트로 전환, 증거 요청 큐·전문가 코드 삭제 | #183, #184 머지 후 | 없음 |
| #186 | Interludeal | L2 입구·Incident 분류·승인·Case 저장과 화면 연결 | 바로 시작, 에이전트 연결은 #184 뒤 | `0100`~`0109` |
| #187 | Juhyeok0603 | L2 분석과 SSH MCP | 바로 시작, 에이전트 연결은 #184 뒤, 실데이터 확인은 #186 뒤 | `0110`~`0119` |
| #188 | Pandyo | 보안 뉴스 수집 계층과 L3 가설 헌팅 | #184(`run_agent`), #186(L2 입구) | `0120`~`0129` |

## 마이그레이션 번호 대역

`main`의 마지막 마이그레이션은 `0094`다. 이슈마다 아래 대역 안에서만 번호를 쓴다. 대역이 없는 이슈에서 마이그레이션이 필요해지면 이 표에 다음 빈 대역(`0130`~)을 먼저 추가하고 담당자들과 합의한다.

| 대역 | 이슈 | 내용 |
|---|---|---|
| `0095`~`0099` | #189 | OCSF 원형 저장 |
| `0100`~`0109` | #186 | `incidents`, `incident_members` 등 Incident·Case 저장 |
| `0110`~`0119` | #187 | `incident_artifacts`, `rule_proposals` |
| `0120`~`0129` | #188 | `threat_news`, `hunt_findings` |

증거 요청 큐 테이블 마이그레이션(`0040`)은 지우지 않는다(#183, #185).

## 이슈 사이 인터페이스

아래 코드 블록은 이슈 본문 그대로다. 바꾸려면 담당자들과 먼저 합의한 뒤 이 문서를 함께 고친다.

### 공통 에이전트 (#184 → #185, #186, #187, #188)

```python
# soc.agent
@dataclass(frozen=True)
class AgentTask:
    level: Literal["l1", "l2", "l3"]   # 프롬프트 오버라이딩과 허용 도구를 고른다
    task: str                           # 예: "l1_promotion", "l1_ticket_verdict", "l2_classify", "l2_analyze", "l3_hunt"
    instructions: str                   # 각 레인이 소유한 작업 프롬프트 내용
    data: Mapping[str, Any]             # 입력 데이터. 코어가 구분자로 감싸 '데이터'로만 전달한다
    output_contract: str                # validate_contract()에 넘길 계약 이름
    subject_type: str                   # Agent Log 주체: alert / ticket / incident / hunt
    subject_id: str
    allowed_evidence_ids: frozenset[str] = frozenset()  # 출력의 근거 ID는 여기나 도구 결과에 있어야 한다

@dataclass(frozen=True)
class AgentResult:
    ok: bool
    output: Any | None                  # 계약 검증을 통과한 생성 모델
    failure: str | None                 # format_error / evidence_id_error / budget_exceeded / provider_error / tool_error

def run_agent(task: AgentTask, *, settings: Settings | None = None) -> AgentResult: ...

class AgentWorker(Protocol):            # 각 레인이 agent_workers 플러그인 그룹에 등록한다
    level: str
    def poll(self, limit: int) -> Sequence[str]: ...   # 판정이 필요한 주체 ID
    def handle(self, subject_id: str) -> None: ...     # run_agent 호출 + 결과 기록
```

- 작업별 프롬프트는 각 레인 폴더(`src/soc/l1/prompts/`, `src/soc/l2/prompts/`, `src/soc/l3/prompts/`)에 두고 `AgentTask.instructions`로 넘긴다. 공통·단계별 프롬프트는 `src/soc/agent/prompts/`에 있다.
- 각 레인은 `AgentWorker`를 `agent_workers` 플러그인 그룹에 등록한다. 실행기는 `[agent.<level>] interval_seconds`마다 그 단계 워커의 `poll` → `handle`을 돈다. `0`이면 그 단계는 자동으로 돌지 않는다(L3 기본 0).
- 허용 도구는 `[mcp.allowed_tools]`의 `l1`·`l2`·`l3` 키로 정한다. 에이전트 도구 코드는 `src/soc/mcp/`(#184에서 `src/soc/l1/mcp/`에서 옮김)에 있다.
- `fake` 백엔드는 작업 이름별 샘플 JSON을 돌려준다. #184 머지 전에는 각 레인이 이 백엔드로 개발한다.

### Ticket 상태와 출처 (L1 → L2, L3 → L2)

- L1 티켓 판정이 이상 행위면 Ticket 상태를 `l2_escalated`로 바꾼다(#185). 오탐은 `closed_fp`, 미만·실패는 보류다.
- L3 헌팅이 위협 존재면 Ticket을 `origin = l3_escalated`, 상태 `l2_escalated`로 만든다(#188).
- L2 워커(level `l2`)는 상태가 `l2_escalated`인 Ticket을 같은 입구로 `poll`한다(#186).

### L2 입구 ↔ L2 분석 (#186 ↔ #187)

#186이 `src/soc/l2/incidents/`에 제공한다.

```python
@dataclass(frozen=True)
class IncidentContext:
    incident: Incident                  # Incident 계약
    tickets: list[Ticket]               # 소속 Ticket
    alerts: list[AlertRecord]           # 소속 Ticket의 알럿
    rejection: L2Review | None          # 마지막 반려(없으면 None)

class IncidentService:
    def pending_analysis(self, limit: int) -> list[str]: ...           # "분석 필요" Incident ID
    def analysis_input(self, incident_id: str) -> IncidentContext: ...
    def finish_analysis(self, incident_id: str, *, failed: bool) -> None: ...
        # "분석 필요" 해제. 성공이면 review_state = awaiting_review, review_round 증가
```

L2 분석 이슈는 `src/soc/l2/analysis/`에 `ArtifactReader.get(incident_id)`와 `ArtifactReader.rule_proposals(incident_id)`를 제공한다.

## 관련 결정

D-008(에이전트 구현), D-009(기본 LLM), D-033(Slack, 데모 제외), D-036(L1 판정 결과), D-042(direct 어댑터 제거), D-043(SSH MCP), D-044(Incident 분류), D-045(L3 입력), D-046(L3 실행 방식). 모두 `docs/decisions.md`.
