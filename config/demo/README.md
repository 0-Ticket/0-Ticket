# 시연 설정 (#79)

AIT 데이터셋의 russellmitchell 웹셸 공격 3분(2022-01-24 03:56:40 ~ 03:59:50 UTC)을 `direct` 어댑터로 재생하는 설정이다. 구간을 고른 이유, 받는 방법, 자르는 명령, 실행 순서는 `docs/milestone-l1.md` "시연 데이터"에 있다.

## 데이터 출처

- AIT Log Data Set V2.0 (Zenodo), CC BY-NC-SA 4.0: russellmitchell Apache 접근 로그와 레이블
- AIT Alert Data Set (AIT-ADS, Zenodo), CC BY 4.0: russellmitchell Wazuh 알럿

이 폴더의 사설 IP, 호스트명, 계정은 위 데이터셋의 가상 회사 값이다. 실제 조직 정보가 아니고, 내부 주소가 없는 시연 샘플이라 예외로 커밋한다(`docs/security-policy.md` 1항). 재생할 데이터 파일은 `data/demo/`에 두고 커밋하지 않는다.

## 파일

| 파일 | 내용 |
|---|---|
| `settings.toml` | `ZT_CONFIG`로 고르는 덮어쓰기 설정: `direct` 재생 파일, 규칙 폴더, 에이전트 허용 도구 |
| `rules/scenarios.toml` | 공격 대상 시나리오 규칙. 기본 샘플 규칙을 대체한다. Wazuh 31104만 시나리오 티켓 |
| `assets.csv`, `users.csv` | Lookup 자산·계정 표. 인트라넷 서버 중요도 5, 방화벽·프록시·DNS는 공용 자산(`shared=true`) |
| `expected.csv` | 대표 알럿 34건의 기대 경로(C21 `path`)와 알럿 결정·티켓 판정 기대값 |
| `expected_counts.csv` | rule_id별 알럿 수, 대표 수, 중복 제거 수 |

```bash
export ZT_CONFIG=config/demo/settings.toml
```
