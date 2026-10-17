import scenarios from '../../../tests/fixtures/frontend/scenarios.json';
import detail from '../../../tests/fixtures/frontend/ticket-detail.json';
import incidentDetail from '../../../tests/fixtures/frontend/incident-detail.json';
import caseDetail from '../../../tests/fixtures/frontend/case-detail.json';
import huntRuleDetail from '../../../tests/fixtures/frontend/hunt-rule-detail.json';
import responses from '../../../tests/fixtures/frontend/api-responses.json';
import type {
  AgentStep,
  AlertRecord,
  Case,
  EventRecord,
  HumanReview,
  HuntFinding,
  Incident,
  IncidentArtifact,
  L2Review,
  NormalizeFailure,
  RawRecord,
  RuleProposal,
  SpecialistFinding,
  Ticket,
} from '../contracts';
import type { Metrics } from '../api/types';

type MockData = {
  tickets: Ticket[];
  alerts: AlertRecord[];
  raw: RawRecord[];
  events: EventRecord[];
  incidents: Incident[];
  artifacts: IncidentArtifact[];
  cases: Case[];
  hunts: HuntFinding[];
  rules: RuleProposal[];
  findings: SpecialistFinding[];
  steps: AgentStep[];
  reviews: HumanReview[];
  l2_reviews: L2Review[];
  normalize_failures: NormalizeFailure[];
};

// JSON enum strings widen on import. Python validates these exact files with
// soc.contracts.validate_contract; this assertion is not runtime validation.
export const data = {
  ...scenarios,
  findings: [
    ...scenarios.findings.filter((item) => item.ticket_id !== detail.ticket.ticket_id),
    ...detail.findings,
  ],
  steps: [
    ...scenarios.steps.filter((item) => item.subject_id !== detail.ticket.ticket_id),
    ...detail.steps,
    ...incidentDetail.steps,
    ...huntRuleDetail.steps,
  ],
  incidents: [...scenarios.incidents, ...incidentDetail.incidents, ...caseDetail.incidents],
  hunts: [...scenarios.hunts, ...incidentDetail.hunts, ...huntRuleDetail.hunts],
  artifacts: [...scenarios.artifacts, ...incidentDetail.artifacts, ...caseDetail.artifacts],
  cases: [...scenarios.cases, ...caseDetail.cases],
  rules: [...scenarios.rules, ...caseDetail.rules, ...huntRuleDetail.rules],
  l2_reviews: [...scenarios.l2_reviews, ...incidentDetail.l2_reviews, ...caseDetail.l2_reviews],
} as unknown as MockData;
export const metrics: Metrics = responses.metrics;
