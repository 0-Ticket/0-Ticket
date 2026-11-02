# 데모 범위 (2026-11-03)

2일 데모까지 만들 범위다. 이 범위 밖은 데모 뒤에 한다. 구조는 `docs/architecture.md` v3(그림과 "박스 그룹과 코드 위치" 표), 계약은 `docs/data-contracts.md`, 결정은 `docs/decisions.md`가 기준이다. 실행 순서는 `docs/demo-run.md`(#183에서 만들고 각 이슈가 채운다)에 둔다. 중간 발표 범위는 `docs/milestone-l1.md`였다.

## 목표와 시연 흐름

**목표**: attack-to-alert 랩 ELK에서 가져온 알럿으로 수집부터 L1 판정, L2 분류·분석·승인과 Case, L3 수동 헌팅과 L2 재진입까지 공통 에이전트 하나로 시연한다.

```
ELK (attack-to-alert 랩, 외부 SIEM)
  → 수집 · 정규화 · 분기 (코드, 연속 실행)
       Alert·Event (RDB, 원본) → OCSF 정규화 → Lookup → 중복 Alert 제거 → 엔티티 추출 → 시나리오 분기
       ├─ 승격 대상(공격 대상) 시나리오 → 시나리오 Ticket
       └─ 그 외 시나리오     → L1 승격 판단 → L1 승격 Ticket / 보류
  → L1 티켓 판정 → 오탐 종결 / 보류 / 이상 행위: Ticket을 L2 상태로
  → L2 Incident 분류 (공용 엔티티 제거 후 새 Incident / 기존 Incident 추가)
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
| | L2 입구, Incident 분류(공용 엔티티 제거 함수 구현 포함, D-044), Human 승인 화면 연결, Case 저장(RDB + Qdrant) | 18, 19, 21, 22, 25 | #186 |
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
| | 공용 엔티티 제거를 알럿 분기 흐름(25의 0단계)에 연결하기. 데모에서는 L2 분류 입력에서만 호출한다(D-044) | 25 | |

## 이슈별 담당과 순서

#182는 다른 이슈가 계획의 근거로 쓰므로 가장 먼저 머지한다. "선행"은 각 이슈 본문의 순서 조건이다.

| 이슈 | 담당 | 내용 | 선행 | 마이그레이션 | 계획에서 정할 것 |
|---|---|---|---|---|---|
| #182 | Pandyo | 결정 대장과 하네스 문서 | 없음 | 없음 | 없음 |
| #183 | uptime-zero | 데이터셋 재생 삭제, 수집 파이프라인 연속 실행(`python -m soc.pipeline`) | 없음 | 없음 | 없음 |
| #184 | Pandyo | 공통 에이전트 코어(`python -m soc.agent`), MCP 코드를 `src/soc/mcp/`로 이동(첫 커밋), 첫날 안에 `fake` 백엔드까지 머지 | 없음 | 없음 | 없음 |
| #189 | uptime-zero | OCSF 정규화 바로잡기 | 병렬 진행, PR과 머지는 #183 뒤 | `0095`~`0099` | 없음 |
| #185 | uptime-zero | L1 승격 판단·티켓 판정을 공통 에이전트로 전환, 증거 요청 큐·전문가 코드 삭제 | #183, #184 머지 후 | 없음 | 없음 |
| #186 | Interludeal | L2 입구·Incident 분류·승인·Case 저장과 화면 연결. 공용 엔티티 제거 함수(25 쪽, `src/soc/l1/entities.py` 옆)를 구현해 L2 분류 입력에서만 호출한다 | 바로 시작, 에이전트 연결은 #184 뒤 | `0100`~`0109` | 없음 |
| #187 | Juhyeok0603 | L2 분석과 SSH MCP | 바로 시작, 에이전트 연결은 #184 뒤, 실데이터 확인은 #186 뒤 | `0110`~`0119` | 없음 |
| #188 | Pandyo | 보안 뉴스 수집 계층과 L3 가설 헌팅 | #184(`run_agent`), #186(L2 입구) | `0120`~`0129` | 없음 |

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

아래 코드 블록은 이슈 본문의 코드와 같다. 레포 포맷 검사(`ruff format`)에 맞춰 공백과 줄바꿈만 바뀌었다. 바꾸려면 담당자들과 먼저 합의한 뒤 이 문서를 함께 고친다.

### 공통 에이전트 (#184 → #185, #186, #187, #188)

```python
# soc.agent
@dataclass(frozen=True)
class AgentTask:
    level: Literal["l1", "l2", "l3"]  # 프롬프트 오버라이딩과 허용 도구를 고른다
    task: str  # 예: "l1_promotion", "l1_ticket_verdict", "l2_classify", "l2_analyze", "l3_hunt"
    instructions: str  # 각 레인이 소유한 작업 프롬프트 내용
    data: Mapping[str, Any]  # 입력 데이터. 코어가 구분자로 감싸 '데이터'로만 전달한다
    output_contract: str  # validate_contract()에 넘길 계약 이름
    subject_type: str  # Agent Log 주체: alert / ticket / incident / hunt
    subject_id: str
    allowed_evidence_ids: frozenset[str] = (
        frozenset()
    )  # 출력의 근거 ID는 여기나 도구의 구조화된 결과 ID 필드에 있어야 한다


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    output: Any | None  # 계약 검증을 통과한 생성 모델
    failure: (
        str | None
    )  # format_error / evidence_id_error / budget_exceeded / provider_error / tool_error


def run_agent(task: AgentTask, *, settings: Settings | None = None) -> AgentResult: ...


class AgentWorker(Protocol):  # 각 레인이 agent_workers 플러그인 그룹에 등록한다
    level: str

    def poll(self, limit: int) -> Sequence[str]: ...  # 판정이 필요한 주체 ID
    def handle(self, subject_id: str) -> None: ...  # run_agent 호출 + 결과 기록
```

- 작업별 프롬프트는 각 레인 폴더(`src/soc/l1/prompts/`, `src/soc/l2/prompts/`, `src/soc/l3/prompts/`)에 두고 `AgentTask.instructions`로 넘긴다. 공통·단계별 프롬프트는 `src/soc/agent/prompts/`에 있다.
- 각 레인은 `AgentWorker`를 `agent_workers` 플러그인 그룹에 등록한다. 실행기는 `[agent.<level>] interval_seconds`마다 그 단계 워커의 `poll` → `handle`을 돈다. `0`이면 그 단계는 자동으로 돌지 않는다(L3 기본 0).
- 허용 도구는 `[mcp.allowed_tools]`의 `l1`·`l2`·`l3` 키로 정한다. 에이전트 도구 코드는 `src/soc/mcp/`(#184에서 `src/soc/l1/mcp/`에서 옮김)에 있다.
- `fake` 백엔드는 작업 이름별 샘플 JSON을 돌려준다. #184 머지 전에는 각 레인이 이 백엔드로 개발한다.
- 근거 ID 규칙(`allowed_evidence_ids`, D-008): 근거로 인정하는 ID는 (1) 작업 입력에 코드가 넣은 ID, (2) 도구가 구조화된 결과의 ID 필드로 돌려준 레코드 ID뿐이다. 로그 본문이나 SSH 출력 같은 텍스트 안의 문자열은 근거 ID로 인정하지 않는다. 텍스트형 도구 결과(SSH 출력 등)는 근거로 인용하지 않고, 참고 정보로만 Artifact 설명에 쓸 수 있다.

### Ticket 상태와 출처 (L1 → L2, L3 → L2)

- L1 티켓 판정이 이상 행위면 Ticket 상태를 `l2_escalated`로 바꾼다(#185). 오탐은 `closed_fp`, 미만·실패는 보류다.
- L3 헌팅에서 위협이 존재하면(`is_anomaly = true`) 근거가 알럿이든 이벤트든 L3 승격 Ticket(`origin = l3_escalated`, 상태 `l2_escalated`)을 만든다. 헌팅 결과는 위협 여부와 관계없이 HuntFinding(C17)으로 남기고, L3 승격 Ticket은 `hunt_id`로 자기를 만든 HuntFinding을 가리킨다. 근거는 `HuntFinding.evidence`에 담고 우리 데이터(알럿·이벤트 참조)만 인정한다(규칙 6). L3 승격 Ticket의 `verdict`는 비워 둔다(C7은 L1 판정 결과로만 쓴다). Ticket의 `entities`에는 헌팅에서 찾은 엔티티를 담는다. C6 계약 변경(#188): `hunt_id` 추가(비어도 됨), `origin = l3_escalated`이면 `alert_ids`가 비어도 됨, 생성 시 바로 `l2_escalated` 전이. 아래 "이슈 사이 규칙" 2·14.
- L2 워커(level `l2`)는 상태가 `l2_escalated`이고 아직 어떤 IncidentMember도 아닌 Ticket만 같은 입구로 `poll`한다(#186). 아래 "이슈 사이 규칙" 5.

### L2 입구 ↔ L2 분석 (#186 ↔ #187)

#186이 `src/soc/l2/incidents/`에 제공한다.

```python
@dataclass(frozen=True)
class IncidentContext:
    incident: Incident  # Incident 계약
    tickets: list[Ticket]  # 소속 Ticket
    alerts: list[AlertRecord]  # 소속 Ticket의 알럿
    rejection: L2Review | None  # 마지막 반려(없으면 None)


class IncidentService:
    def pending_analysis(self, limit: int) -> list[str]: ...  # "분석 필요" Incident ID
    def analysis_input(self, incident_id: str) -> IncidentContext: ...
    def finish_analysis(self, incident_id: str, *, failed: bool) -> None:
        ...
        # 성공이면 "분석 필요" 해제, review_state가 analyzing일 때만 awaiting_review로 바꾸고 review_round 증가. 실패면 "분석 필요"를 유지한다(이슈 사이 규칙 3)
```

- 공용 엔티티 제거 함수는 25 쪽(`src/soc/l1/entities.py` 옆)에 두고, 이번 데모에서는 L2 분류 입력에서만 호출한다. 알럿 분기 흐름(25의 0단계)에 연결하는 것은 데모 범위 밖이다(D-044).
- 재분석 기준은 D-039를 따른다. 새 엔티티나 새 증거 ID(붙은 Ticket의 새 알럿 ID 포함)가 늘면 분석 요청을 만든다(`awaiting_review` 중이면 아래 "이슈 사이 규칙" 4, 분석 실패는 규칙 3). 자동 재분석은 최대 `[l2] max_reruns`(기본 5)까지이고, 한도에 걸리면 정보는 계속 붙이고 표시만 남긴다. 반려에 따른 재분석은 이 횟수에 넣지 않는다(#186).
- `finish_analysis`는 `review_state`가 `analyzing`일 때만 `awaiting_review`로 바꾼다.
- `review_state = human_handling`인 Incident에는 정보만 붙이고, 분석 요청과 새 검토 기회를 만들지 않는다.
- 승인된 Incident(`review_state = approved`, `status = escalated_to_case`)는 열린 Incident 목록(L2 분류 입력)에 들어가지 않는다.
- 열린 Incident는 `status`가 `open`·`investigating`인 Incident다. `human_handling` Incident도 포함되며 정보만 붙는다.

L2 분석 이슈는 `src/soc/l2/analysis/`에 `ArtifactReader.get(incident_id)`와 `ArtifactReader.rule_proposals(incident_id)`를 제공한다.

### L3 헌팅 결과 → L2 (#188 → #186, #187)

```python
class HuntReader:
    def get(self, hunt_id: str) -> HuntFinding | None: ...
```

- #188이 `HuntReader.get(hunt_id) -> HuntFinding | None`을 제공한다.
- #186의 `IncidentContext`에 `hunts: list[HuntFinding]`(소속 Ticket의 `hunt_id`로 읽은 HuntFinding)를 더한다. 위 #186 코드 블록은 이슈 본문 그대로라 이 필드가 아직 없다. #186 본문을 고치면 코드 블록도 맞춘다.
- #187은 `alert_ids`가 빈 Ticket의 근거로 `IncidentContext.hunts`의 `evidence`를 쓴다.
- #188 머지 전에는 #186·#187이 가짜 HuntReader로 개발한다.

## 이슈 사이 규칙 (#182 검토 결정)

2026-11-02 #182 독립 검토에서 정한 규칙이다. 같은 문장을 `docs/decisions.md`의 관련 결정 메모에도 적었다. 바꾸려면 결정 대장과 이 절을 함께 고친다.

1. **근거 ID** (D-008, #184·#187·#188): 근거로 인정하는 ID는 (1) 작업 입력에 코드가 넣은 ID, (2) 도구가 구조화된 결과의 ID 필드로 돌려준 레코드 ID뿐이다. 로그 본문이나 SSH 출력 같은 텍스트 안의 문자열은 근거 ID로 인정하지 않는다. 텍스트형 도구 결과(SSH 출력 등)는 근거로 인용하지 않고, 참고 정보로만 Artifact 설명에 쓸 수 있다.
2. **L3 승격 Ticket** (D-038, #186·#187·#188): L3 헌팅에서 위협이 존재하면(`is_anomaly = true`) 근거가 알럿이든 이벤트든 L3 승격 Ticket(`origin = l3_escalated`, 상태 `l2_escalated`)을 만든다. 헌팅 결과는 위협 여부와 관계없이 HuntFinding(C17)으로 남기고, L3 승격 Ticket은 `hunt_id`로 자기를 만든 HuntFinding을 가리킨다. 근거는 `HuntFinding.evidence`에 담고 우리 데이터(알럿·이벤트 참조)만 인정한다(규칙 6). L3 승격 Ticket의 `verdict`는 비워 둔다(C7은 L1 판정 결과로만 쓴다). Ticket의 `entities`에는 헌팅에서 찾은 엔티티를 담는다. C6 계약 변경(#188): `hunt_id` 추가(비어도 됨), `origin = l3_escalated`이면 `alert_ids`가 비어도 됨, 생성 시 바로 `l2_escalated` 전이.
3. **L2 분석 실패** (D-039, #186·#187): L2 분석이 실패하면 "분석 필요"를 유지하고 다음 주기에 다시 시도한다. 연속 실패가 `[l2] analysis_max_retries`(기본 3)에 걸리면 실패를 표시하고 자동 재시도를 멈춘다(설정 키는 #186이 추가한다).
4. **검토 중 새 정보** (D-039, #186): `awaiting_review` 중에 새 정보가 붙으면 정보만 붙이고 분석 요청은 반려 뒤로 미룬다. 검토 중 새 정보가 붙었다는 표시를 승인 화면에 보여 준다(#186).
5. **L2 입구** (D-044, #186): L2 입구는 상태가 `l2_escalated`이고 아직 어떤 IncidentMember도 아닌 Ticket만 poll한다. 분류 재시도가 한도를 넘으면 그 Ticket만으로 새 Incident를 만든다.
6. **보안 뉴스 근거** (D-045, #188): 보안 뉴스 ID는 가설 출처로만 남기고, 위협 존재의 근거 ID는 Alert·Event와 도구의 구조화된 결과 ID(우리 데이터)만 인정한다.
7. **`human_handling` 처리** (D-039, #186): `human_handling`(두 번 반려)은 시스템 밖에서 처리한다. 데모에서는 화면에 표시만 하고 수동 종결·Case 전환 경로는 만들지 않는다(이후 확장).
8. **분류 저장 재확인** (D-044, #186): L2 분류 결과를 저장할 때 같은 트랜잭션 안에서 대상 Incident가 아직 열려 있는지(`status` `open`·`investigating`, `review_state`가 `approved`가 아님)와 Ticket이 아직 어떤 IncidentMember도 아닌지 다시 확인한다. 확인에 실패하면 분류 실패로 보고 다음 주기에 다시 시도한다(규칙 5의 재시도 횟수에 포함).
9. **재분석·연속 실패 횟수** (D-039, #186): 재분석 횟수(`max_reruns`)는 새 정보로 다시 돌린 분석 중 성공한 것만 센다. 반려로 다시 돌린 분석은 세지 않는다. 연속 실패 횟수(`analysis_max_retries`)는 분석 요청 하나 안에서 연속으로 실패한 횟수이고, 성공하거나 새 정보·반려로 새 분석 요청이 생기면 0으로 돌아간다. 두 카운터는 #186의 L2 내부 테이블(`0100`~`0109`)에 둔다. 화면 표시(재분석 한도 멈춤, 분석 실패 멈춤, 검토 중 새 정보)는 #186에서 C10 계약 필드로 추가한다(`docs/data-contracts.md` "v2 불일치"의 재실행 한도 표시 항목을 여기서 해소).
10. **Case 저장 기준** (D-003, #186): Case 승인은 RDB 저장이 기준이다. Qdrant 저장이 실패해도 승인은 성공으로 두고, `case_id`로 덮어쓰기(같은 ID면 한 건)해 다음 주기에 다시 시도한다.
11. **L3 실행 실패** (D-046, #188): L3 `run_agent`가 실패하면 HuntFinding을 남기지 않고 Agent Log에 실패를 기록한다. 수동 명령은 실패를 출력하고 0이 아닌 종료 코드로 끝난다.
12. **가설 출처 필드** (D-045, #188): 보안 뉴스 ID를 가설 출처로 남기기 위해 C17 HuntFinding에 가설 출처(보안 뉴스 ID 목록) 필드를 추가한다. 계약 변경은 #188에서 한다.
13. **에이전트 입력 한도·실행기** (D-008, #184): 에이전트 입력 한도는 모델 호출 한 번의 입력 전체(쌓인 도구 결과 포함)에 적용하고, 반복은 최대 턴 수로 막는다. 데모는 에이전트 실행기 하나만 지원한다. 실행기를 여러 개 띄우면 같은 건을 두 번 처리할 수 있다.
14. **L3 승격 Ticket의 심각도** (D-038, #186·#188): 알럿 없는 L3 승격 Ticket의 심각도는 `hunt_id`가 가리키는 HuntFinding의 `severity_id`에서 온다. Ticket `priority` = HuntFinding `severity_id` × 자산 criticality(자산 정보가 없으면 1)로 #188이 Ticket을 만들 때 계산한다. Incident `severity_id`를 계산할 때 `alert_ids`가 빈 Ticket은 HuntFinding의 `severity_id`를 쓴다(#186). L3 에이전트가 정한 `severity_id`는 0~6이고, `HuntFinding.evidence`에 우리 데이터 근거가 하나 이상 있어야 Ticket을 만든다(#188).

## 관련 결정

D-008(에이전트 구현), D-009(기본 LLM), D-033(Slack, 데모 제외), D-036(L1 판정 결과), D-042(direct 어댑터 제거), D-043(SSH MCP), D-044(Incident 분류), D-045(L3 입력), D-046(L3 실행 방식). 모두 `docs/decisions.md`.
