# bge-m3 서버 2 배포 사전 점검 결과 (C-08a, #114)

> **박스 8 구현이 아니다.** D-010에서 확정한 로컬 bge-m3를 서버 2에서 띄울 수 있는지(환경 조사)와
> 실제로 기동해 임베딩 응답이 오는지(기동 검증)만 확인한다. VectorDoc 컬렉션 생성·변경, 검색 연결, L1 시작 처리(#105),
> 화면 표시(A-13a)는 하지 않는다.

이 문서에는 서버 2의 주소, 호스트명, 계정 이름, 비밀 값을 적지 않는다. 사람이 서버 2에서 실행한 결과에서 이 값을 지운 뒤
요약해 옮긴다. 서버 2 주소는 조직 설정(`ZT_CONFIG`, 예: `config/local.toml`)의 `[embedder].base_url`에만 둔다.
`config/local.*`은 `.gitignore`에 등록되어 있어 커밋되지 않는다(`git check-ignore -v config/local.toml`로 확인).

| 구분 | 뜻 | 이 문서의 절 |
|---|---|---|
| 환경 조사 | 서버 2의 자원·설치 상태를 명령 출력으로 확인 | 2절 |
| 실제 기동 검증 | 서버 2에서 bge-m3를 띄우고 probe로 임베딩 응답을 확인 | 4절 |

## 1. 도구

- probe: `scripts/probe_embedder.py`. 새 HTTP 코드 없이 기존 `embedders` 레지스트리와 `OllamaEmbedder`
  (`src/soc/store/embedders/ollama.py`, `POST /api/embed`)를 그대로 쓴다. 새 라이브러리 없음.
- 테스트: `tests/store/test_probe_embedder.py` (가짜 embedder와 가짜 Ollama 응답. 실제 Ollama 없이 돈다)

서버 2 로컬에서 실행한다(Ollama가 `localhost:11434`에서 응답하는 경우 기본 설정 그대로 쓸 수 있다).

```bash
ZT_CONFIG=config/local.toml uv run python scripts/probe_embedder.py
```

| 출력 항목 | 뜻 |
|---|---|
| `provider`, `model`, `dimensions` | 설정 `[embedder]` 값 (`base_url`은 출력하지 않음) |
| `samples[].outcome` | `ok`, `embedder_unavailable`(연결·HTTP 실패), `embedder_invalid_response`(JSON·모양 오류), `embedding_dimension_mismatch`(1024차원 아님), `unexpected_error` |
| `samples[].length`·`finite`·`norm`·`latency_ms` | `ok`일 때만. 벡터 길이, 모든 값이 유한한지, L2 norm(소수 4자리), 응답 시간 |
| `ok` | 모든 문장이 `ok`이고 유한값이면 `true` |

- 입력은 코드에 고정한 인공 문장 3개(영문 Ticket, 한글 Ticket, 엔티티 나열)다. 문서용 IP 대역과 `example.com`만 쓰고 로그 원문은 넣지 않는다.
- 벡터 값, `base_url`, 제공자 오류 문구는 출력하지 않는다(`test_success_reports_sizes_and_never_vector_values`,
  `test_base_url_never_reaches_output_from_the_real_ollama_embedder`, `test_unexpected_provider_error_text_is_not_printed`).
- 종료 코드: 0 모두 ok, 1 실패한 문장 있음, 2 설정 오류(설정 파일 없음·제공자 미등록, 요청 없음).
- 벡터 저장소와 Qdrant는 import하지 않는다. 컬렉션을 만들거나 바꾸지 않는다.

## 2. 환경 조사 결과

> **미기록.** Claude Code는 서버 2에 직접 접속하지 않는다. 사람이 서버 2에서 아래 명령을 실행하고
> 주소·호스트명을 지운 출력을 공유하면 이 표를 채운다.

```bash
uname -a
nproc
free -h
df -h
nvidia-smi
ollama --version
ollama list
ollama show bge-m3
```

| 항목 | 값 | 기준 | 판정 |
|---|---|---|---|
| OS·커널 (WSL2 여부 포함) | 미기록 | Linux 또는 WSL2 | 미기록 |
| CPU 코어 수 | 미기록 | 제한 없음 (CPU만으로도 실행 가능, 느림) | 미기록 |
| RAM 전체·여유 | 미기록 | 모델 ~1.2GB + 실행 여유 수 GB | 미기록 |
| GPU 유무·VRAM | 미기록 | 선택. 있으면 VRAM 2GB 이상이면 모델 전체 적재 기대 | 미기록 |
| 디스크 여유 (Ollama 모델 경로) | 미기록 | 모델 ~1.2GB + 여유 | 미기록 |
| Ollama 설치·버전 | 미기록 | `/api/embed`를 지원하는 버전 | 미기록 |
| `ollama list`의 bge-m3 태그·digest | 미기록 | `bge-m3` (설정 `[embedder].model`) | 미기록 |
| `ollama show bge-m3` 파라미터 수·양자화·임베딩 길이 | 미기록 | 임베딩 길이 1024 (설정 `[embedder].dimensions`) | 미기록 |

자원 판정 기준(bge-m3, Ollama): 모델 파일 약 1.2GB, 출력 1024차원, 실행에 수 GB의 메모리 여유가 필요하다.
같은 서버에서 L1 LLM(`granite4-micro-16k`)이나 Qdrant·PostgreSQL을 함께 띄우면 그 몫을 뺀 여유로 판정한다.

## 3. 기동 절차

1. Ollama 설치: 서버 2 OS용 공식 배포본으로 설치한다. 이미 있으면 `ollama --version`만 기록한다.
2. 모델 받기: `ollama pull bge-m3`. 받은 뒤 `ollama list`의 digest를 2절에 기록한다(같은 모델 버전을 다시 받기 위한 기준).
3. 서비스 기동: Ollama 서비스(또는 `ollama serve`)가 `localhost:11434`에서 응답하는지 확인한다.
4. 조직 설정: 서버 2 로컬에서 돌리면 기본값(`http://localhost:11434`)을 그대로 쓴다. 다른 주소가 필요하면
   `config/local.toml`의 `[embedder].base_url`에만 적는다. 이 파일은 커밋하지 않는다.
5. probe 실행: 1절 명령. 결과 JSON을 4절에 옮긴다.

노출 원칙:

- Ollama 포트(11434)는 외부에 열지 않는다. Ollama API에는 인증이 없다.
- 다른 서버가 서버 2의 Ollama에 붙어야 하면 사설망 안에서만 허용하고 방화벽으로 출발지를 제한한다.
  구체적인 주소·규칙은 이 문서에 적지 않는다.

## 4. 실제 기동 검증 결과

> **미기록.** 서버 2에서 bge-m3를 기동하고 1절 probe를 실행한 결과가 아직 없다. 이 상태에서는
> 완료 기준 #2(작은 인공 입력으로 기동과 응답 확인)가 충족되지 않았다.

| 항목 | 값 |
|---|---|
| probe 실행 위치 | 서버 2 로컬 (예정) |
| `ok` | 미기록 |
| `ticket_en` / `ticket_ko` / `entities` outcome | 미기록 |
| `length` (기대 1024) | 미기록 |
| `norm` (Ollama `/api/embed`는 정규화된 벡터를 돌려줘 1.0 근처를 기대) | 미기록 |
| `latency_ms` (첫 요청은 모델 적재 시간 포함) | 미기록 |
| 일부러 Ollama를 멈추고 실행 → `embedder_unavailable` | 미기록 |

## 5. 실행할 수 없는 경우

2절·4절 결과로 아래 중 해당하는 것을 기록한다.

| 원인 | 확인 방법 | 후속 조치 |
|---|---|---|
| 메모리 부족 | `free -h`, 기동 중 OOM | 같은 서버의 다른 모델·서비스 정리 또는 자원 증설. 모델 교체는 아래 결정 검토로 |
| 디스크 부족 | `df -h`, `ollama pull` 실패 | 모델 경로 여유 확보 |
| Ollama 미설치·구버전 | `ollama --version`, `/api/embed` 404 → `embedder_unavailable` | 설치 또는 업그레이드 |
| 모델 미등록 | `ollama list`에 없음, 요청 실패 | `ollama pull bge-m3` |
| 차원 불일치 | `embedding_dimension_mismatch` | 모델 태그 확인. 설정 `dimensions`를 임의로 바꾸지 않는다(C19·컬렉션 차원과 묶임) |
| GPU 없음·VRAM 부족 | `nvidia-smi` | CPU 실행으로 진행하고 응답 시간을 기록. 느리면 후속에서 검토 |

이번 점검 결과: **미기록** (2절·4절이 비어 있다).

## 6. 범위 밖과 후속

| 항목 | 이슈 | 상태 |
|---|---|---|
| 서버 2 환경 조사·기동 검증 (이 문서) | C-08a #114 | 이번 작업. 2절·4절은 미기록 |
| 임베딩 검색 서버 2 운영 경로 | C-08b | **조건부**: 이 문서와 #61의 기존 구현을 확인한 뒤 실제 구현 누락이 있을 때만 등록 |
| L1 시작 처리 | #105 | 후속 |
| F2 유사 Ticket 검색 상태 표시 | A-13a | 후속 |
| 모델 교체 | 결정 검토 (`/soc-decision`, D-010) | 필요할 때만. 이번 작업에서는 바꾸지 않는다 |

`tests/checklist.md`의 K10은 🟡 그대로 둔다. 이 점검은 검색 구현을 바꾸지 않는다.
