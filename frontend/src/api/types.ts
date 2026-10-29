import type {
  AgentStep,
  AlertRecord,
  BranchResult,
  Case,
  EvidenceRequest,
  HumanReview,
  HuntFinding,
  Incident,
  IncidentArtifact,
  L1DecisionRecord,
  L2Review,
  RuleProposal,
  SpecialistFinding,
  Ticket,
} from '../contracts';

// Only HTTP envelopes and request shapes live here. Domain types are generated.
export type Page<T> = { items: T[]; next_cursor: string | null };
export type Pagination = { cursor?: string; limit?: number };
export type ErrorCode = 'not_found' | 'invalid_input' | 'conflict' | 'internal';
export type TicketDetail = {
  ticket: Ticket;
  alerts: AlertRecord[];
  findings: SpecialistFinding[];
  decisions: L1DecisionRecord[];
  evidence_requests: EvidenceRequest[];
  steps: AgentStep[];
  // v2 L1 leaves both empty: people do not review L1 verdicts and grouping belongs to L2.
  reviews: HumanReview[];
  incident_ids: string[];
};
// Box 27: the L1 result of an alert that was held before a Ticket existed.
export type AlertL1Detail = {
  alert: AlertRecord;
  branch: BranchResult | null;
  decisions: L1DecisionRecord[];
  evidence_requests: EvidenceRequest[];
  steps: AgentStep[];
};
export type IncidentDetail = {
  incident: Incident;
  tickets: Ticket[];
  hunts: HuntFinding[];
  artifact: IncidentArtifact | null;
  steps: AgentStep[];
  reviews: L2Review[];
  case_id: string | null;
};
export type CaseDetail = { case: Case; proposal_ids: string[] };
export type HuntDetail = { hunt: HuntFinding; steps: AgentStep[]; proposal_ids: string[] };
export type TicketReviewInput = Pick<HumanReview, 'reviewer' | 'decision'> &
  Partial<Pick<HumanReview, 'reason'>>;
// expected_review_round echoes the C10 review_round the screen received. It is a request
// precondition, not a contract field; the server records the actual C15 round.
export type IncidentReviewInput = Pick<L2Review, 'reviewer' | 'decision'> &
  Partial<Pick<L2Review, 'reject_type' | 'comment'>> & {
    expected_review_round: NonNullable<Incident['review_round']>;
  };
export type RuleReviewInput = {
  reviewer: NonNullable<RuleProposal['reviewer']>;
  decision: L2Review['decision'];
};
export type CasePatch = Partial<Pick<Case, 'status' | 'tasks' | 'lessons'>>;
type MetricsWindow = { from: number; to: number };

// available tells the two answers apart (docs/api-contracts.md "지표"). A union, not
// optional fields: optional ones would let available=true arrive with no counts at all.
export type Metrics =
  | (MetricsWindow & { available: false })
  | (MetricsWindow & {
      available: true;
      tickets_total: number;
      tickets_awaiting_human: number;
      l1_reviews_total: number;
      l1_overturned: number;
      l2_reviews_total: number;
      l2_rejects_by_type: Record<string, number>;
      incident_members_by_source: Record<string, number>;
      normalize_failures_by_reason: Record<string, number>;
    });
