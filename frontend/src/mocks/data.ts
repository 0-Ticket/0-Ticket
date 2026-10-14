import scenarios from '../../../tests/fixtures/frontend/scenarios.json';
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
export const data = scenarios as unknown as MockData;
export const metrics: Metrics = responses.metrics;
