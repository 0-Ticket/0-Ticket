---
issue: 264
date: 2026-11-06
owner: Pandyo
plan: 264-lab-cycle.md
supersedes: []
---

# 랩 ELK 한 사이클을 가짜 ELK로 확인하고 서버 시험 준비를 마쳤다

## 한 일

(작성 중)

## 계획과 달라진 점

- `Settings.ca_cert_path`는 기본값 `""`을 둔 칸으로 만들었다. 기본값이 있어 `Settings`를 직접 만드는 기존 코드는 바꾸지 않아도 된다. 테스트 도우미 `tests/ingest/fake_elk.py`의 `make_settings`에는 `ca_cert_path` 인자를 더했다.
- `[ingest] ca_cert_path` 키가 설정에 없으면 빈 값으로 본다(다른 `[ingest]` 키는 필수). 기존 `local.toml`이나 테스트가 만든 설정 표가 이 키 없이도 그대로 돈다.
- 수집 명령은 CA 파일을 `elk.tls_verify`로 연결 전에 한 번 읽어 보고, `make_client`도 같은 함수로 다시 읽는다. `make_client`의 시그니처를 바꾸지 않으려는 선택이다.

## 다음 사람이 알아야 할 것

- **테스트용 CA 인증서(`tests/fixtures/tls/ca.pem`)는 공개 인증서만 있다.** 개인 키는 만든 뒤 바로 지웠다. 다시 만들 때 명령(개인 키는 임시 폴더에 두고 지운다):

  ```bash
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
    -keyout <임시 폴더>/key.pem -out tests/fixtures/tls/ca.pem -days 3650 \
    -subj "/CN=0-Ticket test CA" -addext "basicConstraints=critical,CA:TRUE"
  ```

  테스트는 TLS 연결을 하지 않고, `httpx.Client`에 넘긴 SSLContext가 이 CA를 담았는지만 본다. 실제 TLS 연결은 서버 확인 항목이다.
- **`ca_cert_path`가 상대 경로면 명령을 실행한 폴더 기준이다.** 서버에서는 절대 경로를 쓴다.
- **httpx는 transport를 직접 넘기면 `verify`를 쓰지 않는다.** SIEM 도구 테스트는 `httpx.MockTransport`를 쓰므로, `verify` 값은 `httpx.Client`를 감싼 spy로 확인한다.
