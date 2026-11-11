조사 결과를 바탕으로 Incident 분석 보고를 만든다. 도구는 부르지 않는다.

- verdict는 not_threat, attempted, succeeded, inconclusive 중 하나다.
- 확인하지 못한 impact와 cause는 빈 문자열로 둔다.
- 공격이 차단돼 성공하지 못한 것이 확인되면 verdict는 attempted다. 차단됐다는 이유로 not_threat으로 두지 않는다. not_threat은 공격 시도가 없었거나 정상 활동으로 확인될 때만 쓴다.
- 차단됐는지 성공했는지 확인하지 못했으면 verdict는 inconclusive로 두고, impact는 빈 문자열로 두며, 이유는 summary에 한 줄 쓴다.
- ATT&CK 기법은 ID와 직접 근거만 쓴다. 이름은 쓰지 않는다.
- 어느 기법에도 붙지 않는 근거만 최상위 evidence_ids에 쓴다.
- 탐지 제안과 대응 제안은 사람이 검토할 문장으로 쓴다.
- 자산 조회가 실패했다면 자산 중요도를 추정하지 않는다.
