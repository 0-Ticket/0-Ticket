# 통합 체크리스트

박스마다 완료 조건을 확인하는 목록이다. 박스를 구현한 PR에서 해당 항목을 확인하고 표시한다.

- K 표는 아키텍처 v2 기준이다. 맨 아래 "#5 계약 구현 검증 결과" 이후 절은 v1 아키텍처 때의 PR 검증 기록이라 고치지 않는다. 그 안의 박스 번호(9, 16, 17 등)는 v1 번호다.

- 기준 시나리오는 `docs/product-spec.md`의 S1~S5다.
- 각 항목은 가능하면 자동 테스트로 만든다. "테스트" 열에 테스트 이름을 적는다.
- 항목 ID는 `K`로 시작한다. 결정 대장의 `D-xxx`와 구분하기 위해서다.
- 상태: `⬜ 미구현` / `🟡 일부` / `✅ 통과`

## 기준 샘플

`tests/fixtures/`에 아래 샘플을 둔다. 박스 작업 때 필요한 것부터 만든다.

| 파일 (예정) | 내용 |
|---|---|
| `alerts_web.jsonl` | S2 흐름: 같은 출발지 `203.0.113.10`의 스캔 → SQL 인젝션 → 웹셸 업로드 시도 알럿. 서로 다른 필드명을 쓰는 시나리오 2종 이상. 공격 대상 시나리오와 그 외 시나리오를 모두 포함 |
| `alerts_cloud.jsonl` | S3 흐름 (보류): 감사 로깅 중지, 비정상 역할 전환 알럿 |
| `alerts_noise.jsonl` | 관계없는 출발지의 알럿 몇 건 (묶이면 안 되는 것), 같은 룰·엔티티 중복 알럿 |
| `events.jsonl` | 웹 접근, 인증 이벤트. S4용 드문 패턴 포함 |
| `lookup/assets.csv`, `lookup/users.csv` | 호스트 6행(`web-01` 중요도 5, 프록시·DNS·DC `shared=true`, 지난 대응 1행, 대역 1행), 계정 3행. 잘못된 표는 `lookup/bad/` (#60) |
| `closed_tickets.jsonl` | 유사 사례 검색용 종결 티켓 몇 건 |
| `llm_responses/` | 가짜 LLM 응답: 정상, 형식 오류, 없는 근거 ID |

## 박스별 확인

v2 박스 기준이다(`docs/architecture.md`). 폐기한 박스(9, 16, 17)의 항목 K11, K19, K20, K21은 ID를 다시 쓰지 않는다.

| ID | 박스 | 확인할 것 | 상태 | 테스트 |
|---|---|---|---|---|
| K1 | 1 (외부) | 범위 밖: Event Source는 외부 SIEM 소관이다. `direct` 재생용 소스 커넥터만 기존 코드 수정 없이 추가할 수 있으면 된다 | ⬜ | |
| K2 | 2 (외부) | 범위 밖: 원본 로그 보관은 외부 SIEM 소관이다. 이 프로젝트의 원본 보관은 K67(Alert·Event 원본) | ⬜ | |
| K3 | 3 | 설정으로 고른 SIEM 커넥터(초기 Wazuh)가 알럿·이벤트를 가져와 `kind`가 붙은 C2로 넘긴다. `direct` 어댑터는 개발·테스트·데모용으로 데이터셋을 같은 입구에 재생하고 같은 흐름이 된다. 운영 설정의 기본값은 `direct`가 아니다 | 🟡 일부 | `test_replays_fixture_config_to_expected_c2`, `test_default_settings_pick_no_adapter_so_direct_is_never_the_default`, `TestDirectContract`, `TestFakeSiemContract`; Wazuh 어댑터는 SIEM 환경 구축 후 같은 `AdapterContract`로 검증 |
| K4 | 4 | 필드명이 다른 시나리오의 알럿이 같은 C3 필드로 정규화되고, 시간·심각도가 변환표대로 바뀐다 | ✅ 통과 | `test_ait_alerts_normalize_to_expected_c3`, `test_fake_scenario_normalizes_by_alias_table_only`(가짜 시나리오 표 파일만 추가), `test_different_field_names_land_in_the_same_c3_fields`, `test_time_formats_convert_to_epoch_ms`, `test_time_without_zone_or_wrong_type_is_bad_value`, `test_severity_map_converts_source_value` (#59) |
| K5 | 4 | 별칭 표에 없는 필드는 `unmapped`에 남고, 실패는 C12로 간다. 이벤트는 C13으로 바뀐다 | ✅ 통과 | `test_unmapped_keeps_unused_fields_nested`, `test_ait_events_normalize_to_expected_c13`, `test_failures_become_c12`, `test_failure_detail_has_no_raw_text`, `test_line_longer_than_parse_limit_is_bad_value_without_running_the_pattern`, `test_overlong_line_fails_and_the_runner_keeps_going`, `test_failures_are_stored_with_their_source`, 실행기 `test_runner_resumes_from_saved_position`, `test_runner_does_not_normalize_a_source_twice`, 저장 `test_normalize_batch_saves_results_failures_and_position`, `test_failed_normalize_batch_saves_nothing`, `test_source_with_failure_is_not_purged`(가짜·PostgreSQL 공통) (#59) |
| K6 | 4 | C3를 OCSF 1.9.0 원형 JSON으로 내보내고 스키마 검증을 통과한다 | ✅ 통과 | `test_ocsf_export_matches_expected`, `test_ocsf_export_passes_ocsf_1_9_0_schema`, `test_alert_record_exports_the_same_way`, `test_host_only_alert_still_has_valid_evidence`; 공식 Detection Finding 스키마(프로필 없음) `tests/fixtures/ocsf/` (#59) |
| K7 | 5 | `web-01`에 중요도 5가 붙고, 프록시는 `shared=true`, 모르는 IP는 `null`이다. 유효 기간이 지난 대응은 쓰지 않는다. Lookup은 RDB에만 저장된다 | ✅ 통과 | `test_web_01_gets_criticality_5_proxy_is_shared_unknown_ip_is_null`, `test_expired_mapping_is_not_used`, `test_exact_ip_beats_narrower_cidr_beats_wider_cidr`, `test_hostname_matches_case_insensitively`, `test_bad_csv_is_rejected_and_table_is_unchanged`, `test_lookup_survives_csv_deletion`, `test_normalize_command_with_all_runs_until_no_source_is_left`(정규화 결합), `test_ticket_priority_uses_criticality_from_lookup`(C6 priority), `test_lookup_handler_returns_c22_result_shape`(큐 lookup); RDB 저장: `TestPostgresLookupStoreContract`, `test_lookups_are_stored_in_postgresql_tables` (#60) |
| K8 | 6 | SIEM 알럿(C2)이 원본 그대로 RDB에 저장되고 4가 읽는다. 엔티티·시간 조회 인덱스가 있다. VDB에 넣지 않는다 | ✅ 통과 | `test_saved_source_record_is_returned_unchanged`, `test_same_source_record_id_is_not_stored_twice`, `test_source_record_update_is_rejected`, `test_list_source_records_pages_by_kind_in_arrival_order`(박스 4가 읽는 경로), `test_entity_time_indexes_exist[alert_records]`, `test_direct_replay_is_stored_and_resumed`, `test_ingest_resumes_from_saved_cursor`; VDB 코드 없음. 박스 4 실행기가 이 경로로 읽는다: `test_runner_resumes_from_saved_position` (#59) |
| K9 | 7 | SIEM 이벤트(C2)가 원본 그대로 RDB에 저장되고 4가 읽는다. 엔티티·시간 조건으로 조회된다. 자체 저장소로 별도 로그 저장소를 쓰지 않는다 | ✅ 통과 | K8과 같은 테스트(event), `test_find_records_by_entity_and_time`, `test_entity_time_indexes_exist[event_records]`; Event도 PostgreSQL(`source_records`, `event_records`)에 저장하고 별도 로그 저장소는 쓰지 않는다 |
| K10 | 8 | Ticket·Case 컬렉션 검색이 유사 사례 상위 k건을 돌려주고, IP·해시는 키워드로 정확히 찾는다. 판정 전 객체가 들어가지 않는다 | 🟡 일부 | `test_qdrant_vector_store_works_without_a_qdrant_server`, `test_qdrant_indexes_decided_ticket_and_supports_exact_and_vector_search`, `test_ticket_doc_uses_c19_ticket_collection_and_exact_entity_keywords`, `test_search_by_ticket_and_entities_sentence_uses_keyword_and_vector_candidates`; Ticket C19 컬렉션·키워드·벡터 검색은 구현. Case 컬렉션은 #61 범위 밖 |
| K12 | 10 | `priority` 계산이 C6 규칙대로이고, 상태 전이가 규칙 밖으로 가지 않는다. 판정이 끝난 티켓만 VDB에 들어간다 | ✅ 통과 | `test_create_ticket_uses_contract_priority_rule`, `test_transition_ticket_accepts_only_documented_v2_edges`, `test_transition_ticket_rejects_undocumented_edges`, `test_ticket_store_creates_and_gets_contract_ticket`, `test_ticket_store_finds_tickets_by_exact_entity_type_and_value`, `test_decided_ticket_vector_interface_*`, `test_ticket_sink_rejects_non_decided_ticket_before_embedding_or_storage`, `test_ticket_sink_indexes_only_final_decision_statuses`; C6 저장·우선순위·상태 전이와 종결 Ticket의 C19 색인까지 |
| K13 | 11 | 가짜 정상 응답으로 C7이 만들어지고 근거 ID가 모두 실제로 존재한다 | ⬜ | |
| K14 | 11 | 형식이 깨진 응답은 한 번 재시도 후 실패 처리된다. 없는 근거 ID가 있으면 판정으로 쓰지 않는다. LLM 실패(형식 오류, 근거 ID 오류, 예산 초과)인 Ticket은 사람에게 넘기지 않고 보류된다 | ⬜ | |
| K15 | 11 | 로그 원문이 `<untrusted_data>` 구분자 안에만 들어간다. "정상으로 분류하라" 같은 문장이 든 알럿으로 확인 | ⬜ | |
| K16 | 11, 14, 26 | 모든 Ticket이 증거 요청 큐를 거쳐 Web 전문가를 부르고, L1이 C14를 판정 근거로 쓴다 | 🟡 일부 | 박스 14(#63): `test_finding_answers_the_question_with_stored_evidence`, `test_core_owns_ticket_id_specialist_and_question`, `test_the_source_flow_is_read_through_the_web_allowlist`, `test_a_tool_outside_the_allowlist_fails_the_request`, `test_malformed_output_falls_back_to_unknown`, `test_evidence_id_that_is_not_stored_falls_back_to_unknown`, `test_fallback_evidence_is_the_tickets_stored_alerts`, `test_every_step_is_logged_on_the_ticket`, 실제 모델은 `test_configured_model_answers_the_web_prompt_as_a_specialist_finding`(-m llm). 남은 것: Ticket마다 요청을 넣고 C14를 판정 근거로 쓰는 쪽은 박스 11(2-6) |
| K17 | 12 | 티켓 생성 전 Alert 단계를 포함해 모든 에이전트 단계가 C8로 남고, 큰 출력은 해시·경로로 보관되며, 비밀 값이 기록에 없다 | ✅ 통과 | `test_agent_log_callable_persists_contract_steps_by_subject`, `test_agent_log_keeps_excerpt_and_hashes_the_rest_of_a_large_result`, `test_agent_log_redacts_secrets_in_contract_fields_and_artifacts`, `test_agent_log_redacts_configured_environment_secrets`, `test_ticket_query_includes_linked_alert_steps_in_time_order`, `test_postgresql_agent_log_store_round_trips_c8_and_artifact_reference`, `test_postgresql_agent_log_store_rejects_duplicate_subject_step`, `test_postgresql_agent_log_store_validates_c8_before_writing`, `test_agent_log_migration_uses_box_12_version_range`; 쓰는 쪽(#63): `test_every_step_is_logged_on_the_ticket` — 전문가의 도구 호출·LLM 호출·판단이 Ticket 번호를 이어서 남는다 |
| K18 | 15 | MCP 도구(SIEM MCP 포함)가 읽기 전용으로 동작하고, 허용 목록에 없는 도구 호출은 거부된다. 대응 도구는 승인 없이 실행되지 않는다 | ✅ 통과 | `test_server_exposes_only_query_siem_as_read_only`, `test_tool_not_in_allowlist_is_rejected_through_mcp`, `test_agent_without_allowlist_exposes_no_tools`, `test_direct_call_rejects_a_tool_the_agent_may_not_use`, `test_limit_above_max_query_limit_is_rejected_before_the_adapter`, `test_adapter_exposes_read_only_methods_only`; 내부 데이터·Web 도메인 도구(#62): `test_every_registered_tool_is_read_only`, `test_http_flow_is_read_only_through_mcp`, `test_get_alert_is_not_granted_to_every_agent`, `test_query_records_limit_above_max_query_limit_is_rejected_before_reading`, `test_http_flow_limit_above_max_query_limit_is_rejected_before_reading`, `test_a_bundle_claiming_a_registered_tool_name_is_rejected`, `test_readonly_store_refuses_to_use_the_writable_url`, `test_readonly_connection_reads_but_cannot_write`(db). 현재 도구는 `query_siem`, `query_records`, `get_alert`, `query_http_flow`이고 모두 읽기 전용이다. 부르는 쪽(#63): `test_a_tool_outside_the_allowlist_fails_the_request` — 전문가는 요청한 에이전트가 아니라 자기 허용 목록으로 부른다. SIEM 교체는 K66 |
| K56 | 25 | 0단계: 중복 알럿은 `count`만 오르고, 공용 엔티티는 빠진다. Incident에 있는 엔티티 → 기존 Incident 추가 + L2 재실행, 공격 대상 시나리오 → 시나리오 티켓, 그 외 → L1 엔티티 조회로 간다. 분기 이유가 남는다 | ⬜ | #69 PR ①: C21 저장소(`branch_store_contract.py`)와 엔티티 변환(`test_entities.py`) 준비. 분기 실행은 PR ② |
| K57 | 25, 18 | L2 입구: 열린 Incident가 없으면 새 Incident가 생기고 SIEM MCP 과거 조회 결과가 붙는다. 있으면 기존 Incident에 추가된다. 노이즈 알럿과 공용 자산은 묶이지 않는다 | ⬜ | |
| K58 | 11 | 엔티티 정보 조회와 Ticket 판정 결과가 승격·종결·L2 승격·보류 중 하나가 되고, 어떤 결과도 사람 확인을 기다리지 않는다. 보류 건은 출처와 관계없이 L3 헌팅 데이터 풀에 들어간다 | 🟡 일부 | #70: 엔티티 조회 승격·보류 완료. Ticket 판정 및 L3 보류 처리는 #72 이후 |
| K60 | 27 | 사람이 L1 결과(승격·보류된 Alert, Ticket 판정, 증거 요청 실패)를 Alert·Ticket 단위로 조회할 수 있다. L1 결과를 바꾸는 API가 없다 | ⬜ | 기록 계약 C23은 #37에서 정의. #69 PR ①: C23 저장소·Ticket 목록·읽기 전용 열기(`l1_decision_store_contract.py`, `ticket_list_contract.py`, `test_postgres_l1_record_stores.py`). 조회 API는 미완료 |
| K59 | 26 | 증거 요청이 PostgreSQL 테이블 큐를 거쳐 도메인별 전문가에게 전달되고, 결과가 요청한 Ticket·Incident에 연결된다 | 🟡 일부 | 실패 처리는 K62. 계약 C22는 #49(`test_evidence_request_branches_accept_valid_values`, `test_evidence_request_condition_errors`). #53 큐: `test_requests_are_claimed_in_arrival_order`, `test_claimed_request_is_not_claimed_twice`, `test_claim_skips_a_row_another_worker_holds`, `test_completed_result_is_readable_by_requester`(가짜 큐·PostgreSQL 공통), `test_siem_mcp_handler_calls_query_siem_with_requesting_agent`, `test_agent_without_query_siem_fails_the_request`, C22 코어 검증 `test_end_before_start_is_rejected`, `test_limit_above_max_query_limit_is_rejected`, `test_finding_for_another_ticket_is_rejected`, 교체 `test_fake_queue_replaces_postgresql_by_setting`. Lookup 처리자(#60): `test_lookup_request_completes_through_the_queue`, `test_lookup_handler_uses_now_when_at_is_null`, `test_unsupported_entity_type_completes_empty_and_warns_with_type_only`. 전문가 전달(#63): `test_request_completes_through_the_queue`, `test_a_request_without_a_domain_goes_to_the_web_specialist`, `test_default_handlers_cover_every_request_type`, 교체 `test_a_fake_specialist_replaces_web_by_registry`. 남은 것: Incident 요청은 L2 범위 |
| K22 | 19, 20 | Incident 생성·갱신으로 L2가 실행되어 C11이 만들어진다. 타임라인이 시간순이고 모든 항목에 근거가 있다. 예산을 넘으면 멈춘다 | ⬜ | 재실행 기준은 K63 |
| K23 | 20 | C11에서 사람이 읽는 보고서(대응 방안, 탐지 룰 제안 포함)가 만들어진다 | ⬜ | |
| K27 | 24 | Incident Artifact에서 C18이 만들어지고, 룰이 문법 검사와 쿼리 변환을 통과하며 백테스트 결과가 붙는다. 21 승인 전에는 SIEM에 반영되지 않는다 | ⬜ | 계약 정리 후 |
| K24 | 21 | 승인·확정이 C15로 남고 Case 생성으로 넘어간다. 반려하면 반려 사유를 입력으로 L2가 재분석하고, 두 번째 반려는 사람 처리로 넘어간다 | 🟡 일부 | #21: 계약과 mock·F3에서 반려 → `analyzing`, 두 번째 반려 → `human_handling` 확인. 반려 사유로 재분석하는 코어 동작은 박스 19·21 구현에서 확인 |
| K25 | 22 | 확정된 Incident로 C16이 만들어지고, 작업 상태가 바뀌며, VDB에 들어간다 | ⬜ | |
| K26 | 23 | 운영자 시나리오, Case, 보류 건으로 가설을 세우고, Event·Alert·SIEM MCP로 검증해 기각 또는 위협 존재를 남긴다. 위협 존재는 L3 승격 티켓으로 L2 입구에 바로 들어간다. 원본 이벤트를 대량으로 LLM에 넣지 않는다 | ⬜ | |
| K61 | 11 | 확신도 임계값이 설정 값(초기 0.8)이다. 엔티티 조회: 이상 → L1 승격 티켓, 미만 → 보류. Ticket 판정: 오탐·이상 → 종결, 이상 행위·이상 → L2 승격, 미만 → 보류. "이상 행위 · 종결" 결과가 나오지 않는다. 설정을 바꾸면 분기가 바뀐다 | 🟡 일부 | #70 엔티티 조회 분기 완료. Ticket 판정은 #72 |
| K62 | 26, 27, 21 | 증거 요청이 설정한 횟수(N, L1·L2 공통)만큼 재시도 후 실패 상태가 된다. L1 요청이면 해당 Ticket이 보류되고 27에서 실패가 보인다. L2 요청이면 Incident가 보류되지 않고 확보한 증거로 분석이 계속되며, "증거 수집 실패" 표시가 21 승인 단계에서 보인다 | 🟡 일부 | #53: `test_failure_retries_n_times_then_fails_with_reason`, `test_retry_count_comes_from_the_setting`, `test_failed_ticket_request_puts_an_open_ticket_on_hold`, `test_failed_request_of_a_finished_ticket_leaves_it_as_is`, `test_failed_alert_request_returns_failure_without_ticket_change`, `test_failure_reason_has_no_raw_text`, `test_start_returns_requests_left_in_progress_to_the_line`. 남은 것: Alert 보류 기록(11, 2-6), 27 표시, L2 요청 처리 |
| K63 | 18, 19 | L2가 찾은 정보는 항상 Incident에 붙는다. 새 엔티티나 새 증거 ID가 늘 때만 L2가 재실행되고, 늘지 않으면 재실행하지 않는다. 최대 재실행 횟수(설정, 초기 5)에 걸리면 정보는 계속 붙고 자동 재실행만 멈추며 표시가 남는다 | ⬜ | |
| K64 | 21, 사용자 접점 | Slack 알림은 L2 분석이 끝나 사람 승인이 필요할 때만 나가고, L1 단계 이벤트로는 나가지 않는다. HTML·마크다운 조각이 든 값이 알림에서 텍스트로만 보인다 | ⬜ | |
| K65 | 10, 11, 23, 25 | Ticket 출처가 세 값(L1 승격 / L3 승격 / 시나리오) 중 하나다. L1 승격·시나리오 티켓은 증거 요청 큐 → L1 판정으로, L3 승격 티켓은 L2 입구로 바로 간다 | 🟡 일부 | `test_create_ticket_preserves_each_origin`, `test_ticket_store_persists_each_contract_origin`; #51에서 출처 값의 생성·저장 확인. 큐·L1·L2 경로는 11·23·25 범위에서 구현 예정 |
| K66 | 3, 15 | 설정으로 고른 SIEM 하나(초기 Wazuh)로 커넥터와 SIEM MCP가 함께 동작한다. 가짜 SIEM 커넥터·SIEM MCP로 바꿔도 코어와 에이전트 코드가 같은 인터페이스로 동작하고, 코어에 SIEM 이름 분기가 없다 | 🟡 일부 | 커넥터: `test_core_runs_the_fake_siem_chosen_by_setting`, `test_core_has_no_siem_name_branch`, `test_core_rejects_plugin_output_that_is_not_c2`; SIEM MCP: `test_same_siem_setting_selects_connector_and_mcp`, `test_fake_adapter_replaces_the_configured_one`, `test_core_has_no_siem_name_branch`(박스 15), `TestFakeSiemMcp`; 실제 SIEM(초기 Wazuh) 어댑터는 SIEM 환경 구축 후 |
| K67 | 4, 6, 7 | 정규화 결과가 원본과 별도 테이블에 저장되고 FK로 원본을 가리킨다. 정규화 후에도 원본 행이 바뀌지 않는다. 원본 보관 기간을 설정으로 바꿀 수 있다(기본 무기한) | ✅ 통과 | `test_normalized_records_point_to_their_source`, `test_record_pointing_at_the_other_kind_is_rejected`, `test_record_without_source_is_rejected`, `test_saving_normalized_results_leaves_sources_unchanged`, `test_referenced_source_cannot_be_deleted`, `test_default_retention_keeps_everything`, `test_retention_purges_old_sources_but_keeps_referenced_ones`, `test_default_settings_pick_postgresql_and_keep_sources_forever`; 박스 4(#59): `test_alert_record_gets_id_count_and_seen_times`, `test_one_normalized_result_per_source`, `test_source_with_failure_is_not_purged` |

## 중간 발표 범위

`docs/milestone-l1.md`의 범위에 해당하는 기존 항목이다. 새 항목을 만들지 않고 위·아래 표의 ID만 모았다. 괄호는 발표에서 확인하는 부분이다.

- 박스: K3, K4, K5, K6, K7, K8, K9, K10, K12, K13, K14, K15, K16, K17, K18, K56(중복 제거·시나리오 분기만), K58, K59, K60, K61, K62(L1 요청만), K65(L1 승격·시나리오 티켓만), K66, K67
- 계약: K53, K54
- 확장성: K31, K33, K35, K37
- 웹 화면: K51(27 조회 화면)

## 전체 흐름

| ID | 확인할 것 | 상태 | 테스트 |
|---|---|---|---|
| K28 | S1·S2 샘플을 넣으면 수집부터 L2 Incident Artifact까지 한 번에 흐른다 (사람 승인은 가짜 입력) | ⬜ | |
| K29 | S3 샘플이 Cloud 전문가를 거쳐 판정된다 (보류) | ⬜ | |
| K30 | S4 샘플이 헌팅부터 L3 승격 티켓, L2 Incident까지 흐른다 | ⬜ | |

## 확장성

| ID | 확인할 것 | 상태 | 테스트 |
|---|---|---|---|
| K31 | 확장 지점마다 가짜 구현체를 등록하고 설정만 바꿔 교체할 수 있다 | 🟡 일부 | `test_fake_implementation_replaces_default`, `test_get_returns_registered_implementation`; 룩업 제공자: `test_fake_lookup_replaces_none_by_setting` (#59), `test_fake_lookup_replaces_csv_by_setting`, `test_enricher_and_queue_handler_use_the_same_provider`, Lookup 저장소 `TestFakeLookupStoreContract` (#60); 나머지 확장 지점은 해당 박스에서 |
| K32 | 외부 패키지의 entry point로 등록한 플러그인을 코어 수정 없이 불러온다 | ✅ 통과 | `test_entry_point_plugin_loads_without_core_import`, `test_broken_entry_point_is_skipped` |
| K33 | 조직 설정 파일(`ZT_CONFIG`)이 기본 설정을 덮어쓰고, 비밀 값은 환경변수에서만 읽는다 | ✅ 통과 | `test_org_config_overrides_only_given_keys`, `test_unknown_key_fails`, `test_secret_literal_in_env_name_field_fails_without_echoing_it`, `test_secret_read_from_env_only`, `test_missing_secret_names_variable_only` |
| K34 | `extensions` 필드의 값이 정규화부터 저장·조회까지 그대로 보존된다 | 🟡 일부 | `test_extensions_map_moves_values_to_extensions`, `test_extensions_survive_normalize_and_store` (#59, 정규화 → 저장 → 조회). 이후 박스(Ticket, 화면) 전달은 해당 박스에서 |
| K35 | LLM 제공자와 모델을 설정만으로 바꿔도 같은 테스트(가짜 응답)가 통과한다 | ✅ 통과 | `test_default_provider_is_registered_and_config_switches_to_fake`, `test_agent_model_override_selects_configured_model` |
| K36 | 조직 폴더의 규칙·프롬프트 파일이 같은 이름의 기본 파일보다 우선한다 | 🟡 일부 | 별칭 표: `test_org_alias_file_overrides_default_by_name`, `test_org_folder_adds_a_new_scenario` (#59). 엔티티 분기 규칙·프롬프트·헌팅 쿼리는 해당 박스에서 |
| K37 | 코어 코드에 특정 구현체 이름으로 분기하는 곳이 없다 | 🟡 일부 | `test_new_registry_has_no_builtins`, `test_entry_point_plugin_loads_without_core_import`; 박스 4 코어: `test_normalize_core_has_no_scenario_or_siem_name_branch` (#59); 나머지 파이프라인 코어는 해당 박스에서 |
| K38 | 플러그인이 등록형 값(소스 종류, 처리 유형, 전문 에이전트, IOC 종류 등)을 새로 등록하면 계약 검증을 통과한다 | ⬜ | |
| K39 | 조직이 프롬프트 파일을 덮어써도 로그 원문 구분자가 유지되고, 플러그인이 대응 동작을 승인 없이 실행할 수 없다 | ⬜ | |

## 웹 화면

화면 작업은 `docs/frontend.md`의 화면 순서(F0 ~ F6)를 따른다. 테스트는 mock 데이터로 한다.

| ID | 화면 | 확인할 것 | 상태 | 테스트 |
|---|---|---|---|---|
| K40 | F0 | 계약 타입이 `frontend/src/contracts/` 한 곳에 있고 필드명·열거형이 `docs/data-contracts.md`와 같다. mock이 `docs/api-contracts.md`의 경로와 응답 모양을 따른다 | ✅ 통과 | `test_frontend_fixture_contracts`, `test_frontend_fixture_references`, `api-contracts.test.ts`, `api-errors.test.ts`, 타입·ESLint 검사 |
| K41 | F0 | 환경변수 하나로 mock과 실제 API를 바꿀 수 있고, 화면 코드는 어느 쪽인지 모른다 | ✅ 통과 | `mock-mode.test.ts`, `api-errors.test.ts`의 MSW 없는 동일 client 검사 |
| K42 | F1 | (v1 기준. F1은 읽기 전용 L1 결과 조회로 바뀔 예정, 후속 이슈) 검토 대기함에 `awaiting_human` 티켓만 나오고, 목록이 `priority` 내림차순 → `created_at` 오름차순 → `ticket_id` 오름차순이며 자산 정보(없으면 "자산 정보 없음")가 보인다 | ✅ 통과 | `api-contracts.test.ts`, `tickets.test.tsx`, `review.test.tsx` |
| K43 | F2 | 판정·확신도·요약 옆에 근거가 있고, 근거를 누르면 해당 알럿·이벤트·원문이 보인다. 권고 조치에 실행 버튼이 없다 | ✅ 통과 | `ticket-detail.test.tsx`: 판정·근거 펼치기·복사, 권고 표시 |
| K44 | F2 | Agent Log가 `step` 순서로 보이고, 전문 에이전트 결과가 판정 옆에 보인다 | ✅ 통과 | `ticket-detail.test.tsx`: 전문 결과·AgentStep 순서·발췌 |
| K45 | F2 | (v1 기준. 판정 뒤집기는 제거 예정, 후속 이슈) 판정을 뒤집을 때 이유가 없으면 보내지 않고, API가 `invalid_input`을 주면 그 내용을 보여 준다 | ✅ 통과 | `ticket-review.test.tsx`: 이유 필수·invalid_input·중복 제출·재조회 |
| K46 | F3 | Incident의 묶음 항목(티켓·헌팅 결과)마다 출처(`source`)와 묶인 이유(`rule`, `matched_entity`)가 보이고, 뺀 항목과 이유가 따로 보이며, 공용 자산이 묶는 기준으로 표시되지 않는다 | 🟡 일부 | `incident-detail.test.tsx`: F3 표시 부분만 통과. 공용 자산 제외 등 실제 묶음 기준은 박스 25 구현에서 확인 (F3 묶음 표시는 v1 기준, 후속 이슈) |
| K47 | F3 | 보고서 타임라인이 시간순이고 모든 항목에 근거 링크가 있다. 반려에는 유형과 코멘트가 필수이고, 두 번 반려되면 "사람 직접 처리"로 표시된다 | ✅ 통과 | `incident-detail.test.tsx`: 응답 순서 유지·근거 링크·2회 반려 표시; `incident-review.test.tsx`: 반려 필수 입력. #21부터 "사람 직접 처리"는 `review_state`=`human_handling`으로만 표시. 실제 재반려 처리(박스 21)는 후속 |
| K48 | F4 | Case 작업의 상태·담당자·마감과 교훈을 수정할 수 있다 | 🟡 일부 | #27: 작업 상태 변경만 `case-tasks.test.tsx`(전체 `tasks` PATCH·재조회·중복 제출·오류 구분). 담당자·마감·교훈 수정은 후속 API/계약 이슈 필요 |
| K49 | F5 | 룰 제안에 문법 검사 결과와 백테스트가 보이고, 승인해도 화면이 SIEM 반영을 하지 않는다 | ✅ 통과 | #29 화면 범위: `rules.test.tsx`, `rule-detail.test.tsx`(문법 결과·백테스트 그대로·null, 배포·실행 버튼 없음), `rule-review.test.tsx`(요청 본문은 `reviewer`·`decision`뿐, 서버 상태 표시). 실제 룰 검사·백테스트·배포 승인(박스 24, K27)은 후속 |
| K50 | F6 | 지표 대시보드가 뒤집은 비율, 반려 유형 통계, 정규화 실패 수를 보여 준다 | ✅ 통과 | #31 화면 범위: `dashboard.test.tsx`(L1 검토·뒤집음 원본 값 나란히 표시, 비율 계산 없음, `l2_rejects_by_type`·`incident_members_by_source`·`normalize_failures_by_reason` 원본 값, 집계 기간 표시). 지표 집계 자체(박스 4·21, v1 16)는 해당 박스에서 확인 |
| K51 | 전체 | HTML·스크립트 조각이 든 로그 원문, LLM 출력, `extensions` 값이 텍스트로만 표시된다 | 🟡 일부 | F1: `tickets.test.tsx`; F2: `ticket-detail.test.tsx`; F3: `incidents.test.tsx`, `incident-detail.test.tsx`; F4: `cases.test.tsx`, `case-detail.test.tsx`, `case-tasks.test.tsx`; F5: `hunts.test.tsx`, `hunt-detail.test.tsx`, `rules.test.tsx`, `rule-detail.test.tsx`(C17·C18에는 `extensions`가 없음), F6: `dashboard.test.tsx`(C10·C16·C17·C18에 든 제목·가설, 새 상태·등록형 값; 대시보드는 `extensions`를 보여 주지 않음); 다른 화면은 후속 검증 |
| K52 | 전체 | 플러그인이 등록한 새 등록형 값과 새 `extensions` 키가 화면 수정 없이 보인다 | 🟡 일부 | F1: `tickets.test.tsx`; F2: `ticket-detail.test.tsx`; F3: `incidents.test.tsx`, `incident-detail.test.tsx`; F4: `cases.test.tsx`, `case-detail.test.tsx`, `case-tasks.test.tsx`; F5: `hunts.test.tsx`, `hunt-detail.test.tsx`, `rules.test.tsx`, `rule-detail.test.tsx`(C17·C18에는 `extensions`가 없음), F6: `dashboard.test.tsx`(C10·C16·C17·C18에 든 제목·가설, 새 상태·등록형 값; 대시보드는 `extensions`를 보여 주지 않음); 다른 화면은 후속 검증 |

## 계약 Schema

| ID | 확인할 것 | 상태 | 테스트 |
|---|---|---|---|
| K53 | `contracts/`의 Schema가 `docs/data-contracts.md`의 모든 객체(C1 ~ C23, 공통 객체)와 필드명·타입·필수 여부·열거형이 같다. 선택 필드는 `required`에 있고 `null`을 허용한다 | ✅ 통과 | `test_schema_contract_coverage`, `test_structure_and_fixtures`, `test_nullable_field_schemas` |
| K54 | 생성 명령 하나로 Python(Pydantic)과 TypeScript 코드가 만들어지고, CI가 다시 생성했을 때 차이가 없다 | ✅ 통과 | `test_generation_reproducible`, `test_all_fixture_types` |
| K55 | 등록형 필드는 Schema에서 `enum`이 아니고, `extensions`는 추가 키를 허용한다. Schema로 표현 가능한 조건을 검증한다. 코어 비즈니스 조건은 해당 박스에서 검증한다 | 🟡 일부 | `test_structural_conditions`, `test_registered_values`, `test_hunt_severity`, `test_runtime_rejects_condition_accepted_by_generated_model`; 코어 비즈니스 검증은 후속 작업 |

## 공통 확인

| 확인할 것 | 상태 |
|---|---|
| 실제 LLM 키 없이 `uv run pytest`가 통과한다 | ✅ 통과 |
| 샘플 데이터와 화면 mock 데이터에 실제 IP·도메인·계정이 없다 (문서용 대역, `example.com`) | ⬜ |

## #5 계약 구현 검증 결과

PR #4가 머지된 `review`와 하네스 결정 확정을 통합했다. 위 표의 K53~K55 검증 근거와 남은 범위는 아래와 같다.

| ID | 상태 | 검증 및 남은 범위 |
|---|---|---|
| K53 | ✅ 통과 | C1~C20·보조 객체 29종을 문서와 수동 대조. `test_schema_contract_coverage`, `test_structure_and_fixtures`, `test_nullable_field_schemas`, `test_all_references_are_local_and_resolve` |
| K54 | ✅ 통과 | `test_generation_reproducible`, `test_typescript_types`, `test_all_fixture_types`; 생성 한 명령 및 CI `--check` |
| K55 | 🟡 일부 | `test_structural_conditions`, `test_condition_branches_accept_valid_values`, `test_field_constraints`, `test_registered_values`, `test_extensions_and_unknown_fields`. Schema로 표현 가능한 구조·필드 조건 완료. 원본 참조 확인·계산·상태 전이 등 코어 비즈니스 검증은 해당 박스에서 완료 |

K34·K38은 이번에 계약 값 보존·새 문자열 허용만 검사했다. 전체 파이프라인과
플러그인 레지스트리는 아직 없으므로 해당 항목을 완료로 표시하지 않는다.
F0 앱·mock·화면은 이번 이슈 범위가 아니며 K40도 완료로 표시하지 않는다.

런타임 계약 검증: `tests/contracts/test_validation.py`에서 공개 함수의 조건 검증·모델 변환,
등록형·확장 값, 입력값 없는 예외, 검증기 재사용, 다른 작업 폴더 및 wheel 리소스를 확인한다.
K55는 여전히 일부이며 코어 비즈니스 검증은 해당 박스에서 완료한다.

## #8 F0 검증 결과

- Node 24.21.0·pnpm 11.9.0에서 고정 lockfile 설치, 프론트 타입·린트·포맷 검사,
  Vitest 30개, Vite 빌드를 통과했다.
- 같은 Node 24 환경에서 기존 계약 도구의 고정 lockfile 설치·타입 검사·재생성 차이 검사를 통과했다.
  Python 전체 366개와 Ruff 포맷·린트 검사를 통과했다.
- K40은 19개 문서 API 경로·응답 묶음, 목록 필터·커서, 오류·검토 요청,
  계약 JSON 샘플 검증을 포함한다. K41은 환경변수에 따른 worker 로딩과
  MSW 유무에 관계없이 같은 API client가 요청하는 것을 확인했다.
- K51은 공통 `PlainText`에 대한 보안 문자열 테스트만, K52는 API에서 새 등록형 값과
  확장 필드를 보존하는 부분만 확인했다. 실제 F1~F6 화면 표시 테스트가 남아 있어 완료로 표시하지 않는다.
- CI에 변경 경로 감지와 프론트 검사 작업을 구성했다. GitHub에서의 실행 결과는 사람이 push한 뒤 확인한다.

### PR #9 리뷰 후 회귀 검증

- MSW는 고정 버전 3.0.3을 유지한다. 이 버전의 공식 옵션은 `onUnhandledFrame`이며,
  `onUnhandledRequest`로 바꾸면 설치된 타입 정의에서 TS2353이 발생함을 확인했다.
- K41: `mock-mode.test.ts`가 실제 MSW에서 유도한 시작 함수 타입과 `bypass` 옵션을 확인한다.
  `api-errors.test.ts`가 테스트 서버의 최초 시작·재시작 후 미등록 요청이 MSW의 `error`
  정책으로 차단되는지 확인한다. 단순 네트워크 실패로는 이 검사를 통과하지 못한다.
- K40: 네 API 오류 코드·네트워크 오류를 유지하면서, 정상/실패 HTTP의 비 JSON 응답,
  본문 읽기 실패, 본문 읽기 중 AbortError 원본 보존을 확인한다.
  기존 취소 테스트는 fetch 이전 취소만 다뤘으며 새 테스트는 실제 `Response.json()`의
  스트림 읽기 오류를 재현한다.
- Node 24.21.0·pnpm 11.9.0에서 프론트 고정 설치·타입·린트·포맷·테스트 **35개**·빌드,
  Ruff 포맷·린트, Python **366개**, 계약 재생성 차이 검사·계약 TypeScript 검사를 통과했다.

### PR #9 동시 검토 요청 회귀 검증

- 수정 전 Ticket·Incident·Rule 모두 본문 파싱을 기다리는 사이 중복 검사를 통과하여
  두 요청이 함께 성공하는 것을 `review-concurrency.test.ts`의 3개 테스트로 재현했다.
- 본문 파싱을 현재 상태 조회보다 먼저 끝낸다. 중복 확인부터 기록·상태 변경 완료까지
  await가 없으며 기존 not_found/conflict/invalid_input 응답 우선순위를 유지한다.
- K40: 두 요청의 본문 읽기를 같은 비동기 경계에서 대기시킨 뒤 `Promise.allSettled`로
  성공 1개와 HTTP 409 conflict 1개를 확인한다. 요청 순서로 승자를 가정하지 않는다.
  Ticket·Incident 기록은 기존보다 정확히 하나 증가하고, Ticket 상태와 Rule 상태·검토자는
  성공 응답과 일치한다. Incident는 기존 F0 동작대로 검토 기록·회차만 갱신하며,
  Rule은 별도 검토 이력 계약 없이 기존 C18 하나의 상태·검토자를 갱신한다.
- 다른 쓰기 핸들러인 Case PATCH에는 중복 검토 선행 조건이 없어 같은 문제가 없다.
  기존 부분 수정 동작을 유지하며 계약·라이브러리 변경은 없다.
- Node 24.21.0·pnpm 11.9.0에서 요청된 전체 검사 통과: 프론트 **38개**(6개 파일),
  Python **366개**, Ruff 포맷·린트, 계약 재생성·타입 검사, 프론트 고정 설치·타입·린트·포맷·빌드.


## #10 F1 검증 결과

- C7은 C6.verdict로 받는다. 생성 계약 타입과 기존 API만 사용한다.
- K42: MSW의 세 정렬 기준, 커서 페이지의 중복·누락 방지, 화면의 응답 순서 유지,
  더 보기 전 다음 페이지 미요청, 폴링 시 불러온 모든 페이지를 새 커서로 갱신함을 확인했다.
- 지표의 현재 대기 건수를 표시하며, 목록 전체 조회나 대기 시간 계산은 하지 않는다.
- 자산·계정, 공용 자산·관리자 계정, null, 등록형 값, 확장 값, HTML·마크다운 문자열,
  ID 복사·상세 링크, 테마 전환, 목록·알럿·추가 페이지 오류와 재시도를 확인했다.
- K45는 F2 전용이며 미완료로 유지한다. F1에는 검토 폼·POST·검토자 설정이 없다.
  `/tickets/:ticket_id`는 F0의 빈 route를 유지한다.
- 프론트 48개 테스트, 타입·린트·포맷 검사·빌드 통과. Python 367개 테스트 및
  `uvx ruff format --check .`, `uvx ruff check .` 통과.
- Node 24.22.0 임시 실행 환경에서 검증했다. 기존 Homebrew Node 24는 simdjson
  공유 라이브러리 누락으로 실행되지 않아 시스템 설치를 변경하지 않고 대체했다.
- Chrome에서 `/review`의 대기 건수, 티켓, 자산·계정 레이아웃을 확인했다.

### #10 승인 계획 재검토

- `tickets.test.tsx`: 세 페이지를 불러온 뒤 실제 폴링으로 새 커서를 따라 모두 갱신한다.
  마지막 페이지 실패 시 이전 목록 전체를 유지하고, 다음 폴링 성공 시 함께 교체한다.
  결과가 한 페이지로 줄면 오래된 페이지를 제거한다. 예상 ID 전체를 비교해
  갱신 전후 중복·누락과 이전 커서 재사용이 없음을 검증했다.
- `/review`, `/tickets`의 실제 요청을 관찰해 기존 tickets·alerts·metrics GET만
  사용하는지 확인했다. F1에 POST·검토자 설정·별도 Verdict 조회는 없다.
- 판정 근거 ID의 복사 버튼 누락을 수정하고 회귀 테스트를 추가했다.
  별도 객체 화면이 정의되지 않은 알럿·원문 ID에는 임의 경로를 만들지 않는다.
- null 계정·자산·판정, 새 Entity 등록형 값, 지역 시간과 epoch ms 툴팁,
  HTML·URL 문자열의 텍스트 표시를 추가 검증했다.
- `review.test.tsx`: 지표 오류를 대기 건수로 대체하지 않으며, 재시도 후 현재 건수
  0도 그대로 표시하는지 확인했다.
- 프론트 54개 테스트와 typecheck/lint/format:check/build, Python 367개 테스트와
  ruff format/check가 통과했다. K45는 F2 미완료, K51·K52는 F1 범위만 확인했다.
- 정렬은 동일 데이터 집합의 커서 순서를 보장한다. 서버 데이터가 요청 도중 바뀌는
  경우의 스냅샷 일관성은 이번 API 계약에 포함하지 않는다.

## #12 Ticket awaiting_human_at 계약 검증

- K53: C6 문서·Schema에 필수 nullable integer 필드를 추가하고 모든 기존 Ticket
  fixture(계약 샘플, 프론트 시나리오, 페이지 응답)를 갱신했다.
  `test_ticket_awaiting_human_at_values`, `test_ticket_awaiting_human_at_invalid_types`,
  `test_ticket_awaiting_human_at_required`로 null·epoch ms 정수 허용, 잘못된 타입·누락 거부를 확인했다.
- `test_ticket_wait_history_round_trip`: 손으로 작성한 미진입·대기·종료 스냅샷의
  null → t1 → t1이 공개 계약 검증과 JSON 직렬화 후 보존됨을 확인했다.
  진입 시각을 created_at·updated_at에서 대신 얻지 않는다. 상태 전이 로직 테스트는 아니다.
- K54: Schema에서 Python `StrictInt | None`과 TypeScript `number | null`을 재생성했다.
  기존 `test_generated_round_trip`, `test_generated_nullable_fields`,
  `test_generated_strict_field_types`, `test_all_fixture_types`와 확장한 `types.test.ts`가 통과했다.
  `test_generation_reproducible` 및 생성기 `--check` 통과.
- K12: 실제 진입 시 기록·상태 종료 후 유지 로직은 후속 박스 10 구현 대상으로 미완료 유지.
  재진입 규칙, 검토 완료 시각·소요 시간, F1/F2 표시 기능은 추가하지 않았다.
- Python 376개, 프론트 54개 테스트 통과. ruff format/check, 계약 TypeScript 검사,
  프론트 typecheck/lint/format:check/build 통과. 기존 공통 integer 검증 정책은 변경하지 않았다.

### #12 승인 범위 재검토

- #10 기준 `b4a2945`와 대조했다. 공통 validator·생성 스크립트·F1 화면·API 호출·mock
  구현은 변경하지 않았고, K55 항목도 동일하다. K12는 실제 기록·유지 구현의 미완료 항목이다.
- 전체 JSON fixture를 재귀 확인했다. 완전한 Ticket 12개 모두 필드를 포함하고
  `validate_contract("Ticket", ...)`를 통과했다. ticket_id 참조 객체 9개에는 필드를 추가하지 않았다.
  MSW는 해당 공유 fixture를 그대로 사용한다.
- Schema의 required + integer/null, Python StrictInt/None, TS number/null을 확인했다.
  생성 재현성 테스트와 생성기 --check가 현재 생성 파일과 일치함을 다시 확인했다.
- 계약 샘플은 미진입 null → 진입 t1 → 종료 t1 세 단계다. 재진입/t2 갱신 규칙은 없고,
  문서에는 현재 상태 전이에 재진입 경로가 없다는 범위 설명만 있다.
- 전체 재검증: Python 376 tests, 프론트 54 tests, ruff format/check, 계약 TS typecheck,
  프론트 typecheck/lint/format:check/build 모두 통과. 구현 수정 없이 검토 결과만 기록했다.

## #15 F2 구현 검증

- K43: 기존 상세 응답의 `ticket.verdict`, `findings`, `steps`, `reviews`,
  `incident_ids`를 사용한다. 별도 조회 API·계약 필드 추가 없음. 근거 종류별 기존
  GET 조회·ID 복사, 원본 연결, null, 지역 시간·epoch ms, 검토 대기 진입 시각을 확인했다.
- K44: subject_id별 step 순서, 접힌 발췌, 판정 옆 전문 분석 결과를 확인했다.
- K45: 동의는 tp/fp로 전송하고 reason·reviewer 누락을 차단한다. overturned를
  요청에 넣지 않는다. 네 API 오류, conflict 최신 조회, 대기 중 이중 제출 방지,
  POST 성공 후 GET 실패를 구분한다. POST를 자동 재시도하지 않는다.
- F1 연계는 POST → GET 재조회 → 상세·검토 기록·두 목록·대기 건수 반영으로 확인했다.
  서버가 FP 요청에 closed_benign을 반환하는 테스트에서도 서버 상태만 표시한다.
  클라이언트 상태 전이 계산·캐시 직접 수정이 없다. 기존 MSW가 상태와 C9를 생성하고
  현재 대기 건수만 mock 상태에서 집계한다. 코어 박스 K12·K19 완료를 뜻하지 않는다.
- K51·K52는 F2 표시 검증을 추가했다. HTML·마크다운·URL·등록형 값·중첩 확장 값이
  plain text로 남으며 모르는 근거 유형의 조회 경로를 만들지 않는다. 전체 상태는 일부 유지.
- Python 377개, Ruff format/check, 프론트 typecheck/lint/format:check/build 통과.
  Node 24.22.0·pnpm 11.9.0, 기본 `pnpm test`(워커 수 미지정)로 검증했다.
- 기본 `pnpm test` 간헐 실패 재검토: 테스트 종료 후 남은 polling interval·진행 중
  Query는 0이었고, Query 캐시 GC 타이머가 파일당 최대 65개 남았다. 테스트용
  QueryClient를 추적해 매 테스트 뒤 취소·정리한다(`src/test/query-clients.ts`).
  F1 폴링 테스트 두 개는 실제 100ms 폴링이 '더 보기' 클릭 직전 버튼을 비활성화하거나
  조회 중 mock을 바꾸는 경쟁 조건이 있어 interval만 가짜 타이머로 제어한다.
  남은 실패는 특정 테스트가 아니라 장비 부하와 함께 나타났다. 실패한 실행은 19~28초,
  통과한 실행은 약 11초였고 1분 load average가 15~43이었다. 같은 부하에서
  `--maxWorkers=4`도 실패해 워커 제한의 필요성은 확인되지 않았다.
  실행 결과에서 1초 기본 대기를 넘긴 첫 조회 세 곳(`review.test.tsx` 두 곳,
  `tickets.test.tsx` 첫 목록)에만 명시적 3초 대기를 두었다. 전역 대기·testTimeout,
  `pnpm test` 스크립트, 워커 수, 폴링 간격, 제품 코드는 바꾸지 않았다. 이후 기본
  `pnpm test` 12회 연속 통과(load average 3~20), 전체 72개.
  테스트를 제외하거나 린트 규칙을 끄지 않았다.
- Chrome에서 라이트·다크 모드의 판정·근거·전문 결과 배치를 확인했다.
  새 라이브러리, 계약·생성 코드 변경 없음. 실제 백엔드 연결과 F3 화면은 후속 범위다.

## #17 F3 구현 검증

- K46 (일부): `GET /api/incidents/{incident_id}`의 `incident.members`를 `excluded`로만 나눠
  포함·제외 항목을 표시한다. 항목마다 `source` 배지, `rule`, `matched_entity`(null이면 "없음"),
  `excluded_reason`, 티켓·헌팅 링크를 확인했다. 공용 자산을 묶는 기준으로 쓰지 않는 것은
  Correlation(박스 17)의 계산 규칙이라 F3에서 완료 처리하지 않는다.
- K47: C11 `timeline`은 계약이 보장하는 응답 순서 그대로 표시하고 다시 정렬하지 않는다.
  fixture와 Python 테스트에서 시간순 응답을 확인했다. 근거는 alert·event·raw를 기존
  조회 API로 펼치고 `ticket`은 `/tickets/:id`로 링크한다. 모르는 등록형 `ref_type`은
  복사 가능한 텍스트로만 두고 조회 경로를 만들지 않는다. 반려는 `reject_type`과
  `comment`가 없으면 보내지 않는다. 응답 C15에서 `decision=reject`가 2건 이상이면
  "사람 직접 처리" 표시만 붙인다. 상태 값을 만들지 않고 검토 폼 가능 여부에도 쓰지 않는다.
  실제 재반려 처리(박스 21)는 후속 범위다.
- 검토 폼은 `case_id`가 있거나 `closed_benign`·`escalated_to_case`일 때만 비활성화한다.
  그 밖의 판단은 API에 맡긴다. 요청은 `reviewer`, `decision`, `reject_type`, `comment`만
  보내고 `round`는 보내지 않는다. 응답의 `round`만 표시한다. 중복 제출 방지, 네 API 오류,
  POST 자동 재시도 없음, 성공·conflict 후 상세·목록·지표 재조회, 저장 후 재조회 실패
  구분을 확인했다. mock은 L2Review와 round만 기록하며 Incident 상태 전이와 Case 생성은
  하지 않는다(박스 21·22 후속).
- K51·K52: 제목·요약·제외 사유·타임라인·추정 원인·권고·IOC URL·검토 코멘트·발췌·
  `extensions`의 HTML·마크다운·URL 문자열이 plain text로 남고, 새 Entity·Ioc·Evidence
  등록형 값과 새 `extensions` 키가 원래 문자열로 보이는지 확인했다. 권고에는 실행 버튼이 없다.
- `tests/fixtures/frontend/incident-detail.json`을 추가하고 `validate_contract()`와 참조 ID를
  검증했다(`test_incident_detail_fixture_contracts_and_references`).
- Node 24.21.0·pnpm 11.9.0에서 typecheck/lint/format:check/build 통과, 기본 `pnpm test`
  5회 연속 통과(전체 92개). Python 테스트와 ruff format/check 통과.
  장비 부하(load average 50 이상)에서는 F1·F2·F3 테스트 일부가 5초 제한을 넘기는 것을
  관찰했다. 부하가 내려간 뒤에는 통과했다. 테스트 제한 시간과 워커 수는 바꾸지 않았고,
  F3 검증 테스트는 짧은 테스트로 나눴다.

### #17 최종 재검토

- 책임 경계: `handlers.ts`, `ticket-list.tsx`, `agent-log.tsx`는 변경하지 않았다. mock은
  L2Review·round 기록과 기존 conflict 처리만 하며 Incident 상태 전이·Case 생성을 하지 않는다.
  화면은 묶음·severity·status·round·Case 생성 여부를 계산하지 않는다.
- 보강: 이중 클릭 시 POST가 정확히 1회인지, 성공·conflict 후 metrics·Incident 목록 Query가
  invalidate되고 다른 오류에서는 재조회하지 않는지 단언을 추가했다. metrics 재조회를
  지운 변형에서 두 테스트가 실패하는 것을 확인했다. 결정 라디오를 `fieldset`/`legend`로 묶었다.
- untrusted 문자열 경로에 HTML 주입·마크다운 렌더링·자동 링크가 없다. 링크는 고정 내부 경로와
  `encodeURIComponent`한 ID뿐이다.
- Node 24.21.0에서 기본 `pnpm test` 10회 연속 통과(92개, load average 5~19, 회당 약 10초).
  앞선 간헐 실패는 load average 28~55의 CPU 경합에서만 관찰됐다.

### #17 PR #18 리뷰 대응: L2 재검토

- 계약·API에 새 검토 기회 신호가 없음을 확인했다. 검토 건수·round·시각 비교로 추론하지 않는다.
- mock: Case가 있거나 `closed_benign`·`escalated_to_case`이면 `conflict`이고 기록하지 않는다
  (`api-contracts.test.ts`의 `returns conflict for ...` 3건). 이 규칙을 지운 변형에서 실패를 확인했다.
  그 밖에는 세션마다 Incident당 1회다. 기존 F0 API·동시성 테스트는 Case가 있는 `in_sample` 대신
  열린 Incident(`in_manual`, `in_web_campaign`)를 대상으로 바꿨다. 지운 테스트는 없다.
- 화면: `in_escalated`(Case 없음) 비활성화, 성공 후 같은 화면 비활성 → 다시 마운트하면 열림 →
  같은 기회에 다시 보내면 `conflict` 표시와 기록 1건 유지를 확인했다(`incident-review.test.tsx`).
- 후속: #21 "[Contract] Incident L2 재검토 가능 상태 신호 정의". K24·K47의 실제 재검토 흐름은 박스 21에서 확인한다.

- 안정성: `incidents.test.tsx` 첫 목록 조회에 3초 대기를 넣을지 재현으로 비교했다. 정상 부하
  (load average 8 미만)에서는 대기 없이 5회 모두 통과했다. 1초 대기를 넘겨 실패한 경우는
  F1·F2 테스트도 함께 실패하던 고부하(회당 20~30초)에서만 나와서, 대기를 추가하지 않았다.
  전역 testTimeout, 워커 수, `pnpm test` 명령은 바꾸지 않았다.

## #19 플러그인 레지스트리 검증 결과

- `src/soc/plugins.py` 하나로 확장 지점당 레지스트리 하나(`PluginRegistry(<그룹>)`)를 만든다.
  `get(name)`이 설정값으로 구현체를 고르는 경계다. 설정 파일을 읽는 일(D-015, 설정 로더)은 범위 밖이다.
- 중복 등록은 같은 객체면 무시, 다른 객체면 `DuplicatePluginError`다. entry point가 레포에
  이미 있는 이름을 주장하면 그 플러그인을 건너뛰고 `load_errors`에 기록한다. 발견이 먼저
  일어나도 레포 등록이 이긴다(`test_repo_registration_wins_after_discovery`). 외부 패키지가
  기본 구현체를 조용히 가로채지 못한다.
- entry point 로딩 실패는 건너뛰고 경고와 `load_errors` 기록으로 끝낸다. 깨진 패키지 하나가
  같은 그룹의 다른 플러그인을 막지 않는다.
- 서로 다른 외부 패키지가 같은 이름을 주장하면 아무것도 싣기 전에 `DuplicatePluginError`로 멈춘다.
  발견 순서가 구현체를 고르지 못한다(`test_external_duplicate_fails_in_any_order`). 그 이름을 레포가
  이미 등록했다면 레포가 이기고 외부 선언은 `load_errors`에 남는다.
- 그룹 이름은 `EXTENSION_POINT_GROUPS`로 생성 시점에 검증한다. `docs/extensibility.md`의 확장 지점
  13개만 받고, `siems` 같은 오타는 즉시 `ValueError`다. 확장 지점(코어 구조)을 검증하는 것이지
  구현체 이름을 박아 넣는 것이 아니며, 테스트가 문서 표와 상수를 대조한다.
- K38(등록형 값)은 데이터 값의 레지스트리로 구현체 레지스트리와 다른 것이라 이번 범위에서 빼고
  ⬜로 둔다. 해당 값 검증은 후속 이슈에서 이 레지스트리 위에 올린다.
- `tests/contracts/test_generation.py` 2건(`test_generation_reproducible`, `test_typescript_types`)은
  Windows 로컬에서만 실패한다. 생성 파일의 CRLF 체크아웃과 `subprocess`의 `pnpm`(`pnpm.cmd`) 실행 때문이며,
  `origin/review`를 그대로 받은 작업 트리에서도 같은 2건이 실패한다. 이번 변경과 무관하다.

## #20 F0~F3 UI 개선 검증

- 기능·API·계약·Query·mock·검증 로직은 그대로다. 바뀐 것은 스타일·배치·공통 표시 부품뿐이다.
  `src/api/`, `src/mocks/`, `src/contracts/`, `contracts/`, `tests/fixtures/`는 수정하지 않았다.
- 기존 테스트는 고치거나 지우지 않았다. 기존 화면 문구, 접근성 이름(`{id} 복사`, `다크 모드`, region 이름),
  `data-testid`, `<article>` 구조, 값 표시 횟수를 그대로 유지했다.
- 추가: `src/app/layout.test.tsx` — 주 메뉴 현재 위치, `/review`·`/tickets` 목적 문구,
  상세 화면의 목록 경로 링크, 배지 tone(모르는 값은 원래 문자열·neutral). 구현 전 5건 실패를 확인했다.
- K51·K52 관련: 신뢰할 수 없는 문자열은 계속 텍스트 노드로만 표시한다. 발췌·로그는 고정폭 블록에
  plain text로만 두고 수준·URL을 해석하지 않는다. `dangerouslySetInnerHTML`·`innerHTML`·외부 링크 없음.
  권고에는 "권고 · 실행하지 않음"만 있고 실행 버튼이 없다.
- 브라우저(mock) 확인: 다섯 화면을 라이트·다크로 보고, 375px 폭에서 가로 넘침이 없음을 확인했다.
  콘솔 오류 없음.
- 명령: `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `pnpm build` 통과. `pnpm test` 103개
  3회 연속 통과(load average 24~27). `uvx ruff format --check .`, `uvx ruff check .`,
  `uv run pytest`(378개) 통과.
- 환경 메모: 로컬 Homebrew `node@24`가 라이브러리 누락(simdjson)으로 실행되지 않아 Node 22.22.3으로
  확인했다. CI의 Node 24에서 다시 확인이 필요하다. 고부하(load average 20 이상)에서는 기존 코드에서도
  1초 기본 대기를 넘는 간헐 실패가 관찰됐다.

### #20 최종 검토

- 범위: `origin/review` 대비 `contracts/`, `src/`, `frontend/src/{api,mocks,contracts}`, 라우터·providers,
  `package.json`·잠금 파일·`.nvmrc`, `tests/fixtures/` 변경 없음. L1·L2 검토 폼의 상태·검증·제출 코드는
  `return` 이전까지 바이트 단위로 같다. `display.ts`의 라벨 22개, 위험·심각도 라벨, 등록형 라벨,
  `localTime`, "사람 직접 처리" 판단(반려 2건 이상, 표시 전용)이 같다. tone은 표시 색일 뿐이다.
- 발견·수정: (1) lg 이상에서 sticky 검토 영역이 화면보다 높으면 제출 버튼이 가려질 수 있었다
  (1100×600에서 ticket 상세 570px > 552px). 최대 높이와 자체 스크롤을 줘서 제출 버튼에 닿게 했다.
  (2) Lookup 자산 소제목이 h2 다음 h4로 건너뛰었다. h3로 바꾸고 `layout.test.tsx`에 heading 단계
  검사 3건을 추가했다(수정 전 `/review`에서 실패 확인).
- 375px: 다섯 화면 모두 가로 넘침 없음, 주 메뉴는 가로 스크롤, 검토 영역은 sticky 없이 본문 아래에 놓인다.
- 명령: `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `pnpm build` 통과. `pnpm test` 106개
  3회 연속 통과(load average 4~11). `uvx ruff format --check .`, `uvx ruff check .`, `uv run pytest` 378개 통과.
- Node 24: 프로젝트 고정값은 `.nvmrc` 24, `engines` `>=24 <25`이며 CI는 `setup-node`의
  `node-version-file: frontend/.nvmrc`로 설치한다. 로컬 `/opt/homebrew/opt/node@24`는 예전 `node` 24.7.0을
  가리키는 링크인데, simdjson 4.6.4 업그레이드로 `libsimdjson.26.dylib`가 없어져 실행되지 않는다.
  로컬 Homebrew 문제이며 프로젝트 코드와 무관하다. 로컬 확인은 Node 22.22.3이고, PR CI의 Node 24 통과가 필수 조건이다.

## #21 L2 재검토 가능 상태 신호

- 계약 변경: C10 Incident에 `review_state`(`analyzing`, `awaiting_review`, `approved`, `human_handling`)와
  `review_round: int | null`을 필수 필드로 추가했다. `status` enum과 전이는 그대로다. C15 `round`는 구조를
  바꾸지 않고 "그 검토가 처리한 기회의 회차를 코어가 기록"으로 설명만 고쳤다. 요청 본문에
  `expected_review_round`(사전 조건, 저장하지 않음)를 추가했다. 역할 구분 표는 `docs/data-contracts.md` C15와
  `docs/api-contracts.md` "L2 검토 기회 (#21)"에 있다.
- `review_state`는 C10 `status`처럼 닫힌 enum이다. 등록형 값이 아니므로 플러그인 값 `example.custom`은
  거부된다(`test_incident_review_state_is_closed_enum_like_status`, 짝 검사의 `example.custom` 케이스).
- Schema 짝 검사(`test_incident_review_state_round_pairing`, `conditions.json` 4건,
  `test_incident_review_signal_errors`): `awaiting_review`+1 이상 유효, `awaiting_review`+null·0 무효,
  `analyzing`·`approved`·`human_handling`+정수 무효, 오류 path/rule이 `/review_round`·`type|minimum`,
  `/review_state`·`enum`이고 입력값을 담지 않는다. 생성 Pydantic 모델의 `review_round` 0·모르는 상태 거부.
- fixture: `in_sample`·`in_escalated` approved, `in_web_campaign` 1회차 대기, `in_reanalysis` 1회 반려 후 재분석,
  `in_second_round` 1회 반려 후 2회차 대기(새 C11 있음), `in_manual`·`in_benign` 2회 반려 후 human_handling.
  `test_incident_review_fixtures_follow_box21_flow`가 시나리오별 (상태, 회차, 반려 수)와 C15 이력·C11·Case·`status`의
  일관성을 확인한다(회차 연속, 승인은 마지막 검토, 검토 이력이 있으면 `open` 아님, Case는 approved에만,
  awaiting·analyzing은 `investigating`). 화면은 이 값을 계산하지 않고 받은 그대로 쓴다.
- mock: 세션 `reviewed` Set을 Incident 검토 판단에서 뺐다(티켓 검토는 그대로). `review_state`가
  `awaiting_review`가 아니면 conflict, `expected_review_round` 누락·정수 아님은 invalid_input, 회차가 다르면 conflict.
  성공하면 `round`에 열린 회차를 기록하고 approve → approved, 첫 반려 → analyzing, 두 번째 반려 → human_handling,
  `review_round` null. `status`·Case는 바꾸지 않는다. 같은 기회에 동시 요청은 하나만 성공한다
  (`review-concurrency.test.ts`). 회차가 다른 경우의 검사를 지운 변형에서 `api-contracts.test.ts`가 실패했다.
- 화면: 폼은 `review_state`가 `awaiting_review`일 때만 열리고, 받은 `review_round`를 `expected_review_round`로
  그대로 보낸다. 폼은 열린 기회마다 새로 마운트된다. 답한 기회에서는 계속 잠기고 제출 중(재조회 대기 포함)에는
  다시 보내지 않는다. 같은 화면에서 재조회로 새 회차가 열리면 빈 폼으로 다시 열린다. 이 다시 마운트를
  없앤 변형에서 `incident-review.test.tsx`가 실패했다. 반려 2건이 있어도 `review_state`가 아니면
  "사람 직접 처리"를 표시하지 않고, 검토가 없어도 `human_handling`이면 표시한다(`incident-detail.test.tsx`).
  목록·상세에 `review_state` 배지를 `status` 배지와 나란히 둔다.
- 최종 검토(#21 3단계)에서 고친 것:
  (1) fixture 모순: `in_escalated` approved인데 승인 C15가 없음 → 1회차 승인 추가. `in_second_round`가
  검토 대기인데 C11이 없음 → C11 추가. `in_manual`(검토 2건)·`in_sample`(승인·Case 있음)의 `status`가 `open`
  → 각각 `investigating`, `escalated_to_case`. 이를 잡지 못하던 fixture 검사를 강화했다.
  (2) 오류 우선순위 테스트 추가(`applies the documented L2 error precedence`): not_found > 닫힌 기회 conflict
  (본문이 잘못돼도) > invalid_input > 회차 불일치 conflict. 회차 검사를 본문 검증 앞으로 옮긴 변형에서 실패 확인.
  우선순위의 의도를 `docs/api-contracts.md`에 적었다.
  (3) stale tab 테스트 추가(`rejects a stale tab that still holds an answered round`): A가 1회차를 반려한 뒤
  B의 `expected_review_round=1` 제출은 conflict이고 상태가 바뀌지 않는다. 2회차가 열린 Incident에 1을 보내도 conflict.
  (4) `docs/frontend.md`의 #17 기록(종결·Case로 비활성, 세션당 1회 mock)에 "#21에서 대체됨" 표시.
- 동시성: mock의 유일한 `await`는 본문 파싱이고, 상태 확인부터 C15 기록·상태 변경까지는 한 동기 구간이다.
  `review-concurrency.test.ts`의 `race`는 두 요청의 본문 파싱이 모두 도착할 때까지 막았다가 동시에 풀어 주므로
  요청 순서에 의존하지 않는다. 진 요청은 `review_state` 조건으로 conflict를 받는다.
- 브라우저(mock, dev 서버): F3 목록·상세에서 `status` 배지와 `review_state` 배지가 나란히 보이고,
  `in_manual`·`in_reanalysis`·`in_sample`은 폼 비활성과 이유 문구, `in_second_round`는 활성. 375px iframe에서
  목록·상세 가로 넘침 없음, 검토 영역은 sticky 없이 본문 아래(#20 구조 그대로). 콘솔 오류 없음.
- 명령: `uvx ruff format --check .`, `uvx ruff check .`, `uv run pytest`(416개),
  `generate_contracts.py --check`(exit 0, 생성 파일 차이 없음), `pnpm --dir tools/contracts typecheck`,
  `pnpm typecheck`, `pnpm lint`, `pnpm format:check`, `pnpm build` 통과. 기본 `pnpm test`(118개, timeout·worker·명령 변경 없음):
  최종 5회 연속 통과(load average 22~28).
- 간헐 실패 구분: load average 33~38에서 기본 `pnpm test`의 1~6건이 실패했다. #21과 무관한 F1·F2 테스트
  (티켓 목록·상세, 신뢰할 수 없는 문자열 표시)도 함께 실패했고, 실패는 모두 기본 1초 `findBy`/`waitFor` 대기 또는 5초 테스트
  제한 초과였다. 잘못된 값 단언 실패나 conflict/기록 건수 불일치(race의 신호)는 없었다. F3·API 파일만 20회 돌렸을 때
  19회 통과했다. 나머지 1회(load average 약 18~20)는 실패 메시지를 기록하지 못해 원인을 단정하지 않는다. 폼을 두 번 채우던 재오픈 테스트의 두 번째 제출을 짧은 승인으로
  줄였다(검증 내용 같음, 대기 시간 설정 변경 없음).
- 환경 메모: 로컬 Node 24가 실행되지 않아(#20 메모와 같음) Node 22.22.3으로 확인했다. CI Node 24 확인 필요.
- 범위 밖: 실제 코어(박스 21)의 상태 전이·회차 부여, 박스 19의 새 C11 → 기회 열기, 박스 22 Case 생성,
  `human_handling` 이후 처리.


## #29 F5 구현 검증

- 범위: `/hunts`, `/hunts/:hunt_id`, `/rules`, `/rules/:proposal_id`와 룰 승인/반려. 기준 브랜치 `test`(`origin/test`와 같은 커밋에서 시작).
- K49는 화면 범위에서만 통과로 표시했다. K27(박스 24 룰 검사·백테스트·배포 승인)과 K30(S4 헌팅 → 룰 제안 흐름)은
  실제 박스 동작이라 화면을 만들었다는 이유로 표시하지 않았다.
- 현재 계약에 없는 이슈 요구(C17 `extensions`·Entity·상태, C18 요약·위험도, 룰 검토 사유·기록 목록)는 구현하지 않았고
  `docs/frontend.md` "#29에서 하지 않은 것"에 적었다. 완료로 표시하지 않는다.
- fixture: `tests/fixtures/frontend/hunt-rule-detail.json`, `test_hunt_rule_fixture_contracts_and_references`.
- 기존 테스트 기대값 갱신(동작 변경 아님): 메뉴 항목 2개 추가(`layout.test.tsx`), 새 fixture로 `is_anomaly=false`·
  `deployed` 필터 결과가 비지 않게 됨(`api-contracts.test.ts`, 데이터 기준 비교로 바꿈).
- 3단계에서 고친 것:
  (1) fixture 모순: `ht_web`이 `rule_candidate=false`인데 룰 제안 2건의 근거였다 → `true`로 고치고, 룰 제안의 근거 헌팅은
  `rule_candidate`이며 근거보다 늦게 만들어지고 백테스트 기간이 제안 전이라는 검사를 Python 테스트에 더했다
  (되돌린 변형에서 `rp_web_shell`로 실패 확인). 조사 단계는 `subject_type=hunt`이고 헌팅 결과 이전 시각인지도 확인한다.
  (2) 룰 상세의 관련 Incident가 `hunt_id`가 있으면 `case_id`를 무시했다. 계약상 둘 다 있을 수 있으므로(`anyOf`) 임의
  우선순위를 없애고, 있는 참조를 각각 따라가 한 영역에 출처와 함께 보여 준다(`rule-detail.test.tsx` 두 참조 테스트).
  (3) 테스트 추가: 헌팅 목록이 행마다 헌팅·이벤트·Incident 상세를 조회하지 않음(`hunts.test.tsx`), 근거 이벤트는 펼칠 때만
  문서 경로로 조회하고 모르는 `ref_type`은 조회하지 않으며 조회 실패가 헌팅 화면 전체를 막지 않음(`hunt-detail.test.tsx`).
  (4) F5 테스트 파일의 요청 기록 리스너 정리를 테스트 끝 줄에서 `afterEach`로 옮겼다. 테스트가 중간에 실패해도 다음
  테스트로 새지 않는다. 공용 setup·Vitest 설정·명령·timeout·worker 수는 바꾸지 않았다.
- 기본 `pnpm test` 반복(설정 변경 없음): 부하가 낮아진 뒤(1분 load average 9 이하에서 시작) 3회 연속 통과(177개, 24~28초).
  그 전 측정: load 5~26에서 2회 통과, load 26~40에서 1회 F3 `incidents.test.tsx` 1건 실패(1초 `findBy` 대기 중 목록이
  아직 로딩 중). 다른 실행과 겹친 1회는 load 80에서 3건 실패. 고부하(약 50) 구현 단계에서는 매번 다른 1~15건이 실패했다.
  실패는 모두 1초 대기나 5초 제한 초과였고, 값 단언 실패·요청 건수 불일치·테스트 사이 상태 누수는 없었다. 실패한 테스트는
  F5와 무관한 F1~F4 파일에도 고르게 퍼졌다. 그래서 race·cleanup 문제가 아니라 장비 부하로 판단한다. F5 테스트 5개 파일이
  더해져 suite가 무거워진 것은 사실이며, #21 기록과 같은 기존 부하 민감성이다.
- 브라우저(mock dev 서버, 같은 출처 iframe 375px·1280px × 라이트·다크, 28조합): `/hunts`, `/hunts/ht_cloud_login`(Incident 없음),
  `/hunts/ht_web`(Incident 있음), `/rules`, `/rules/rp_web_shell`(draft), `/rules/rp_web_approved`, `/rules/rp_case_deployed`.
  모든 조합에서 페이지 가로 넘침 없음, 화면 폭을 넘는 요소 없음, 테마 배경 적용(라이트 `rgb(243,245,247)`, 다크 `rgb(12,17,23)`),
  좁은 메뉴에서 "헌팅"·"룰 제안" 현재 링크가 메뉴 띠 안에 보임, `h1` 하나와 섹션 `h2`, 이름 없는 입력 없음(검토자·승인·반려
  label), script·img·iframe·b·i·외부 링크 요소 없음. `sigma_rule`·`siem_query`·발췌 `pre`는 `pre-wrap` + 내부 스크롤로
  화면 안에 머문다. draft에만 "검토 제출"이 있고 approved·deployed에는 버튼이 없다. 콘솔 오류 없음.
- 명령: `uvx ruff format --check .`, `uvx ruff check .`, `uv run pytest`(418개), `pnpm typecheck`, `pnpm lint`,
  `pnpm format:check`, 기본 `pnpm test`(177개, 3회 연속), `pnpm build` 통과.
- 환경 메모: 로컬 Homebrew Node 24가 라이브러리 누락(`libsimdjson`)으로 실행되지 않아 Node 22.22.3으로 확인했다.
  프로젝트 설정은 바꾸지 않았다. CI Node 24 통과가 머지 조건이다.

## #31 F6 구현 검증

- 범위: `/` 운영·지표 대시보드. 기준 브랜치 `test`(`origin/test` a68fb4f와 같은 커밋에서 시작).
- K50은 화면 범위에서 통과로 표시했다. 지표 값 자체의 집계(박스 4 정규화 실패, 16 뒤집기, 21 반려)는 실제 박스 구현에서 확인한다.
- K51·K52는 F6 근거만 더하고 상태는 기존 정책대로 🟡 일부를 유지했다.
- 테스트: `dashboard.test.tsx` 16개. heading 구조와 진입 링크, 지표의 대기 건수, 지표 원본 값과 `%` 없음, 빈 지표 묶음,
  첫 페이지 표시용 집계·모르는 값·응답 순서, 최대 5건, `next_cursor` 표시, 요청 목록(문서의 목록·지표 GET 각 1회,
  상세·`normalize-failures` 요청 없음), Case·Rule·지표 단독 실패와 그 Query만 재시도, 지표 갱신 실패 뒤 이전 대기 건수를
  보여 주지 않음, 영역별 로딩·빈 상태, untrusted 문자열, 메뉴 `end`(`/cases`, `/rules`, `/hunts/ht_web`, `/tickets/…`에서 비활성)와
  키보드 이동. 모든 테스트 끝에 요청 메서드가 GET뿐인지 확인한다(읽기 전용).
- 깨뜨려 본 확인: 대기 건수를 고정값으로, 상단 항목을 역순으로 바꾸면 각각 7건, 3건이 실패했다. `end`를 지워도 통과한다.
  React Router가 `/` 링크를 하위 경로에서 활성으로 보지 않기 때문이며, 테스트는 동작(`/`에서만 활성)을 확인한다.
- 3단계에서 고친 것: 지표가 한 번 성공한 뒤 갱신이 실패하면 Ticket 영역이 이전 대기 건수를 현재 값처럼 계속 보였다
  (브라우저에서 발견). 오류가 있으면 이전 값 대신 "확인할 수 없음" 안내를 보이게 하고 테스트를 더했다(수정 전 코드에서 실패 확인).
  같은 이유로 갱신에 실패한 목록·지표 영역에 이전 값이 남아 있으면 "마지막으로 받은 값" 안내를 붙이고 테스트를 더했다.
- 브라우저(mock dev 서버, 같은 출처 iframe 375px·1280px × 라이트·다크, `/`): 4조합 모두 페이지 가로 넘침 0, 화면 폭을 넘는
  요소 없음, 375px에서 영역 6개가 한 열(1280px은 두 열, 지표는 전체 폭), 테마 배경(라이트 `rgb(243,245,247)`, 다크
  `rgb(12,17,23)`), `h1` 하나와 영역 `h2` 6개(더 깊은 heading 없음), 이름 없는 링크·버튼 없음, 좁은 메뉴에서 "대시보드"가
  현재 링크로 띠 안에 보임, `%` 없음, 외부 링크 없음. 상태 확인은 iframe의 `fetch`를 감싸 Case·지표 500, 헌팅 빈 목록,
  Incident 제목에 긴 `<script>`·URL 문자열과 80자 모르는 상태, `next_cursor`를 주었다: 오류는 두 영역에만, 헌팅 빈 상태,
  "불러온 8건 기준 · 더 있음", 긴 문자열·상태가 텍스트로 줄바꿈되어 넘침 없음, script 실행·요소 생성 없음. 요청은 문서의 GET 6개뿐.
  Case 재시도는 `/api/cases`만, 지표 재시도는 `/api/metrics`만 보냈다(한 번은 30초 폴링과 겹쳐 다른 목록도 기록되어, 단독으로
  다시 확인). 창이 백그라운드라 TanStack Query가 재시도·폴링을 멈춰서 검사용 iframe에서만 `visibilityState`를 visible로 두었다.
  새로고침 후 콘솔 오류 없음. 본문 링크 26개 모두 Tab으로 접근 가능(`tabIndex` 음수·disabled 없음).
- 기본 `pnpm test` 반복(설정·timeout·worker 변경 없음):
  - 3단계 중간 코드(193개): 1분 load average 3.8~29에서 3회 연속 통과(29~34초).
  - 최종 코드(195개): 5회 중 3회 통과, 2회는 각 2건 실패. 대기 중 1분 load average는 다른 앱 때문에 20 아래로 내려가지 않았다
    (시작 시점 9~44). 실패는 매번 다른 F2·F3 파일이었다(`ticket-review`·`incident-review` 5초 초과, `incidents`·`incident-detail`
    1초 `findBy` 대기 중 아직 로딩). 그 사이 `cases.test.tsx`도 한 번 "Case 불러오는 중…" 상태로 1초 대기를 넘겼다.
    값 단언 실패, 요청 수 불일치, 테스트 사이 상태 누수는 없었다. 실패한 4개 파일만 따로 2회 돌리면 모두 통과했다(39개).
    F6 테스트는 모든 실행에서 통과했다. #29 기록과 같은 부하 민감성으로 판단한다. F6 16개가 더해져 suite가 무거워진 것은 사실이다.
  - 정상 부하에서 3회 연속 통과는 최종 코드로 다시 확인하지 못했다. CI 통과로 확인한다.
- 기존 테스트 기대값 갱신(동작 변경 아님): 메뉴 첫 항목 "대시보드" 추가, `/` heading 단계 검사 추가(`layout.test.tsx`).
