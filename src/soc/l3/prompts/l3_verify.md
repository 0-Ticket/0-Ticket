[작업: L3 가설 검증]
<data> 안의 가설(hypothesis)이 우리 환경에서 실제로 일어났는지 window 기간의 Alert·Event를 도구로 조회해 확인한다.

- attack_techniques는 가설과 관련된 ATT&CK 기법 ID와 이름이다. window는 조회할 기간(from, to, UTC epoch 밀리초)이다.
- 가설을 지지하는 기록과 함께 가설과 맞지 않는 기록도 찾는다.
- result는 다음 중 하나다.
  - confirmed: 가설대로 위협이 있었다. 그 사실을 보여 주는 Alert·Event ID(alt_, evt_)를 근거로 든다
  - rejected: 조회해 보니 가설과 맞지 않는다. 그렇게 판단한 근거 ID를 든다
  - inconclusive: 근거가 부족해 판단할 수 없다
- confidence는 0~1 사이의 확신도다. reason에는 판단 이유를 짧게 적는다.
- evidence_ids에는 근거 장부에 있는 ID만 쓴다. entities에는 확인한 IP·호스트·계정 등을 적는다.

답은 아래 모양의 JSON 하나다.
{"result": "rejected", "confidence": 0.8, "reason": "이유", "evidence_ids": ["evt_…"], "entities": [{"type": "ip", "value": "203.0.113.10", "role": "src"}]}
