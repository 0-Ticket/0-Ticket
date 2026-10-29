# Box 8 로컬 bge-m3 실행 점검 (#114)

검증일: 2026-10-30

## 범위

D-010에서 확정한 `bge-m3`의 로컬 실행 환경과 기본 임베딩 응답을 확인했다. VectorDoc 컬렉션 생성·변경과 검색 연결, L1 시작 처리는 이 점검 범위에 포함하지 않는다.

## 환경

- 운영체제: Windows 11 Home
- CPU: AMD Ryzen 5 7500F 6-Core Processor
- 시스템 메모리: 31.6 GiB
- GPU: NVIDIA GeForce RTX 4060 Ti, 8188 MiB
- Ollama: 0.40.11
- 모델: `bge-m3:latest` (`790764642607`), 디스크 표시 크기 1.2 GB

## 기동 및 응답 확인

- 확인 당시 로컬 Ollama 서버 프로세스는 `ollama.exe serve`였고, 앱 프로세스는 `ollama app.exe --hide --fast-startup`으로 실행 중이었다.
- 요청 전 `ollama ps`에는 적재된 모델이 없었다.
- 입력 `synthetic local embedding readiness check`로 로컬 `/api/embed`에 `bge-m3:latest` 임베딩을 요청했다.
- 응답은 유한한 실수 1024개였다.
- 요청 후 `ollama ps`에서 모델이 GPU 100%, 689 MB로 적재된 것을 확인했다.

따라서 로컬 서버에서 모델을 요청 시 적재하고 임베딩을 반환하는 것을 확인했다. 실제 기업 로그, 비밀 값, 조직별 설정은 사용하지 않았다.
