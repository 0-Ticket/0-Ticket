# 수집(ingest) 테스트 (#218)

ELK 수집 명령(`soc.ingest`)의 테스트를 계층별로 모았다. 계층은 "외부 연결이 있는가"로 나눈다.

| 계층 | 폴더 | 실행 | 외부 연결 |
|---|---|---|---|
| 단위 | `unit/` | `uv run pytest tests/ingest/unit` | 없음(가짜 ELK·가짜 저장소) |
| DB | `db/` | `uv run pytest -m db tests/ingest/db` | PostgreSQL(`DATABASE_URL`) |

공용 도구: `fake_elk.py`(가짜 ELK·가짜 저장소). 두 계층이 같이 쓰므로 이 폴더에 둔다.
fixture 파일은 저장소 관례대로 `tests/fixtures/ingest/`에 있다.

## 단위 테스트 (`unit/`)

### `test_config.py`: 설정 읽기와 검사
- `test_default_config_reads_into_settings`: 저장소의 `config/default.toml`이 Settings로 읽힌다.
- `test_local_overrides_default_and_only_ingest_is_returned`: `local.toml`이 같은 키를 덮어쓴다.
- `test_missing_ingest_section_gives_empty`: [ingest]가 없으면 빈 표를 돌려준다.
- `test_bad_settings_are_rejected`: 잘못된 값(0 이하, 빈 키, 중복 대상 등)은 ConfigError다.

### `test_elk.py`: ELK 조회 클라이언트 (`soc.ingest.elk`)
- 요청과 페이징
  - `test_client_sends_api_key_and_does_not_follow_redirects`: API 키 헤더, 리다이렉트 끔.
  - `test_pages_follow_search_after_and_hits_are_untouched`: `search_after`로 넘기고 hit을 바꾸지 않는다.
  - `test_full_page_asks_again_and_empty_page_ends`: 꽉 찬 페이지는 다음을 부르고, 빈 페이지에서 끝난다.
  - `test_start_time_becomes_range_gte`: 체크포인트 시각이 `gte` 조건이 된다.
- 실패 종류 (`IngestError`)
  - `test_search_status_is_failure_and_pit_is_closed`: 검색 실패 뒤에도 PIT를 닫는다.
  - `test_pit_open_status_is_failure`: PIT 열기 실패.
  - `test_redirect_is_not_followed`: 리다이렉트는 실패로 본다.
  - `test_failed_close_does_not_hide_pages`: PIT 닫기 실패가 받은 페이지를 가리지 않는다.
  - `test_oversized_response_is_too_large`: 크기 상한 초과.
  - `test_request_timeout_and_network_error`: 제한 시간과 연결 오류.
  - `test_slow_response_stops_at_deadline`: 응답 마감 시간 초과.
  - `test_malformed_search_response_is_response_shape`, `test_fixture_without_sort_is_response_shape`, `test_malformed_pit_response_is_response_shape`: 응답 모양이 틀리면 `response_shape`.

### `test_run.py`: 실행 루프, 종료 코드, 명령 진입점 (`soc.ingest.run`, `__main__`)
- 저장과 재개
  - `test_pages_are_saved_with_checkpoint`: 페이지마다 원본과 체크포인트를 저장하고, `ok` 이력 한 행을 남긴다.
  - `test_next_run_resumes_from_checkpoint_and_skips_stored`: 다음 실행은 체크포인트에서 이어가고 중복을 넣지 않는다. 이력은 실행마다 쌓인다.
  - `test_empty_result_keeps_checkpoint_and_records_ok_run`: 결과가 없으면 체크포인트를 그대로 두고, `ok`(0페이지·0건) 이력을 남긴다.
- 실패 처리
  - `test_bad_record_stops_with_contract_rejected`: 계약에 맞지 않는 원본이면 그 대상을 멈추고, cursor는 마지막 성공 페이지에 남고, `contract_rejected` 이력을 남긴다.
  - `test_siem_failure_keeps_checkpoint_and_other_sources_run`: ELK 실패 시 체크포인트는 그대로이고, 다른 대상은 계속 돈다. 대상마다 이력(`http_status`, `ok`)이 남는다.
  - `test_first_page_failure_records_run_without_checkpoint`: 첫 페이지부터 실패하면 체크포인트 없이 실패 이력만 남는다.
  - `test_db_error_is_db_error_and_failed_run_record_is_ignored`: DB 오류는 `db_error`이고, 이력 쓰기 자체의 오류는 무시한다.
  - `test_failed_run_record_does_not_change_success`: 이력 쓰기가 실패해도 성공 결과와 저장한 원본·체크포인트는 그대로다.
  - `test_failure_prints_name_and_kind_only`: stderr에는 대상 이름과 종류만 나온다.
- 출력과 종료 코드
  - `test_format_results_has_counts_only`: 출력 줄에 건수와 종류만 있다.
  - `test_missing_env_is_exit_2_without_connecting`: 환경변수가 없으면 종료 코드 2, 연결하지 않는다.
  - `test_bad_elk_url_is_exit_2`: 계정 정보가 든 주소는 종료 코드 2.
  - `test_main_runs_sources_and_never_prints_secrets`: 전체 실행이 끝나도 비밀 값이 출력에 없다.
  - `test_db_connect_failure_is_exit_1`: DB 연결 실패는 종료 코드 1.

## DB 테스트 (`db/`, 마커 `db`)

### `test_store_db.py`: 저장 계층 (`soc.ingest.store`)
- `test_page_and_checkpoint_are_saved`: 페이지와 체크포인트가 함께 저장된다.
- `test_same_id_in_two_indexes_is_stored_twice`: 같은 `_id`라도 인덱스가 다르면 별도 문서다.
- `test_saving_same_documents_again_keeps_originals`: 같은 문서를 다시 저장해도 처음 원본을 유지한다.
- `test_contract_rejection_writes_nothing`: 계약 위반이면 아무것도 쓰지 않는다.
- `test_rejected_checkpoint_writes_no_records`: 체크포인트가 틀리면 원본도 쓰지 않는다.
- `test_db_failure_on_checkpoint_rolls_back_records`: 체크포인트 쓰기가 실패하면 원본까지 되돌린다.
- `test_runs_accumulate_and_leave_checkpoint_alone`: 실행 이력은 실행마다 한 행씩 쌓이고 체크포인트를 바꾸지 않는다.
- `test_rejected_run_writes_nothing`: 계약에 맞지 않는 이력(원문 outcome)은 쓰지 않는다.
- `test_checks_reject_broken_rows`: `ingest_checkpoints`의 CHECK 제약이 잘못된 행을 막는다.
- `test_run_checks_reject_broken_rows`: `ingest_runs`의 CHECK 제약(코드 모양 outcome, 음수 건수, 시작보다 이른 종료 등)이 잘못된 행을 막는다.

### `test_run_db.py`: 실행 전체를 실제 DB로
- `test_rejected_page_rolls_back_and_next_run_resumes`: 거부된 페이지는 롤백되고, 다음 실행이 같은 위치에서 이어간다. 이력에 `contract_rejected`, `ok`가 차례로 쌓인다.
- `test_first_page_failure_and_empty_run_leave_history_only`: 첫 페이지 실패와 0건 성공은 체크포인트 없이 이력 행만 남긴다.
- `test_failed_run_record_keeps_saved_pages`: 이력 쓰기가 DB 오류로 실패해도 실행은 성공이고 원본·체크포인트는 커밋돼 있다.

### `test_links_db.py`: 알럿↔원본 이벤트 연결 (`soc.ingest.store.link_by_refs`, `raw_links`)
- `test_links_are_saved_and_many_to_many_works`: 알럿 하나가 이벤트 여럿을, 이벤트 하나가 알럿 여럿에 연결된다.
- `test_saving_the_same_pairs_again_links_nothing_and_is_not_pending`: 같은 쌍을 다시 넘기면 새로 넣지 않고 보류하지도 않는다.
- `test_missing_event_is_pending_then_links_after_it_arrives`: 이벤트 원본이 없으면 보류로 돌려주고, 들어온 뒤 다시 넘기면 연결된다.
- `test_missing_alert_is_pending`: 알럿 원본이 없어도 보류로 돌려준다.
- `test_pending_pair_does_not_block_the_others`: 보류된 쌍이 있어도 나머지 쌍은 연결된다.
- `test_only_the_given_profile_and_kind_are_matched`: 다른 프로필의 원본이나 kind가 다른 원본은 연결하지 않는다.
- `test_failure_rolls_back_the_whole_batch`: 중간에 실패하면 이미 넣은 연결도 되돌린다.
- 연결 키를 알럿 문서의 어느 필드에서 읽는지는 아직 확인되지 않아 이 테스트들은 합성 `siem_ref`만 쓴다.

