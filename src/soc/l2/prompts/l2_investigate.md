주어진 Incident 문맥과 조회 구간 안의 기록을 조사한다.

- 확인한 사실만 시간순 timeline에 쓴다.
- 새 엔티티는 근거 ID와 함께 쓴다.
- 각 timeline과 entity 항목에 직접 뒷받침하는 근거 ID를 붙인다.
- 어느 항목에도 붙지 않는 근거만 최상위 evidence_ids에 쓴다.
- 조회와 도구 호출은 data.window.from부터 data.window.to까지만 사용한다.
- data.related는 전체 구간에서 고르게 뽑은 주변 기록이다. 여기서 단서를 찾아 필요한 지점을 조회한다.
- 시간 범위 조회 도구는 호출마다 data.max_range_days일 이내의 구간을 사용한다.
- 자산 조회가 실패했다면 자산 중요도를 추정하지 않는다.
