# 0-Ticket SOC

**AI 에이전트가 SIEM 알럿을 판정하고, 사고 단위로 묶어 보고서를 쓰고, 알럿이 없는 위협까지 찾아내는 SOC 파이프라인.**
분석가는 알럿을 하나씩 보는 대신, 에이전트가 만든 사고 분석을 검토하고 승인합니다.

> **상태: 새로 시작.** 2026-11-02에 개발 방식을 바꿔 처음부터 다시 만들고 있습니다.

## 하는 일

| 단계 | 에이전트가 하는 일 | 사람이 하는 일 |
|---|---|---|
| 수집 · 정규화 | (코드) 외부 SIEM에서 알럿을 가져와 OCSF로 정규화하고 저장한다 | |
| L1 · 알럿 판정 | 알럿을 조사해 종결하거나, L2로 올리거나, 보류한다 | 결과를 조회한다 |
| L2 · 사고 분석 | 관련 알럿을 사고로 묶고 타임라인·영향 범위·원인·대응 방안·탐지 룰 제안을 만든다 | 승인·확정한다 |
| L3 · 위협 헌팅 | 알럿이 없는 위협을 가설로 세워 검증하고, 찾으면 L2로 넘긴다 | |

원칙과 큰 흐름은 [docs/architecture.md](docs/architecture.md), 쓰는 도구는 [docs/decisions.md](docs/decisions.md)에 있습니다.

## 시작하기

Python 3.13과 [uv](https://docs.astral.sh/uv/)가 필요합니다.

```bash
uv sync                 # 의존성 설치
cp .env.example .env    # 필요한 값만 채움
uv run pytest           # 테스트
docker compose up -d    # 개발용 PostgreSQL·Qdrant
```

## 기여하기

개발 흐름, 브랜치 규칙, AI 코딩 도구와 함께 일하는 방법은 [CONTRIBUTING.md](CONTRIBUTING.md)에 있습니다.

## 라이선스

Apache-2.0. [LICENSE](LICENSE)를 보세요.
