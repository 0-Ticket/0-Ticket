import type {
  AlertRecord,
  Case,
  EventRecord,
  HumanReview,
  HuntFinding,
  Incident,
  L2Review,
  NormalizeFailure,
  RawRecord,
  RuleProposal,
  Ticket,
} from '../contracts';
import { request } from './client';
import type {
  CaseDetail,
  CasePatch,
  HuntDetail,
  IncidentDetail,
  IncidentReviewInput,
  Metrics,
  Page,
  Pagination,
  RuleReviewInput,
  TicketDetail,
  TicketReviewInput,
} from './types';

const id = encodeURIComponent;
export const api = {
  tickets: (
    query: Pagination & {
      status?: Ticket['status'];
      handling_type?: string;
      min_priority?: number;
    } = {},
    signal?: AbortSignal,
  ) => request<Page<Ticket>>('tickets', { query, signal }),
  ticket: (value: string, signal?: AbortSignal) =>
    request<TicketDetail>(`tickets/${id(value)}`, { signal }),
  alert: (value: string, signal?: AbortSignal) =>
    request<AlertRecord>(`alerts/${id(value)}`, { signal }),
  event: (value: string, signal?: AbortSignal) =>
    request<EventRecord>(`events/${id(value)}`, { signal }),
  raw: (value: string, signal?: AbortSignal) => request<RawRecord>(`raw/${id(value)}`, { signal }),
  incidents: (
    query: Pagination & { status?: Incident['status']; created_by?: Incident['created_by'] } = {},
    signal?: AbortSignal,
  ) => request<Page<Incident>>('incidents', { query, signal }),
  incident: (value: string, signal?: AbortSignal) =>
    request<IncidentDetail>(`incidents/${id(value)}`, { signal }),
  cases: (query: Pagination & { status?: Case['status'] } = {}, signal?: AbortSignal) =>
    request<Page<Case>>('cases', { query, signal }),
  case: (value: string, signal?: AbortSignal) =>
    request<CaseDetail>(`cases/${id(value)}`, { signal }),
  hunts: (query: Pagination & { is_anomaly?: boolean } = {}, signal?: AbortSignal) =>
    request<Page<HuntFinding>>('hunts', { query, signal }),
  hunt: (value: string, signal?: AbortSignal) =>
    request<HuntDetail>(`hunts/${id(value)}`, { signal }),
  rules: (query: Pagination & { status?: RuleProposal['status'] } = {}, signal?: AbortSignal) =>
    request<Page<RuleProposal>>('rules', { query, signal }),
  rule: (value: string, signal?: AbortSignal) =>
    request<RuleProposal>(`rules/${id(value)}`, { signal }),
  normalizeFailures: (
    query: Pagination & { reason?: NormalizeFailure['reason'] } = {},
    signal?: AbortSignal,
  ) => request<Page<NormalizeFailure>>('normalize-failures', { query, signal }),
  metrics: (query: { from: number; to: number }, signal?: AbortSignal) =>
    request<Metrics>('metrics', { query, signal }),
  reviewTicket: (value: string, body: TicketReviewInput) =>
    request<HumanReview>(`tickets/${id(value)}/reviews`, { method: 'POST', body }),
  reviewIncident: (value: string, body: IncidentReviewInput) =>
    request<L2Review>(`incidents/${id(value)}/reviews`, { method: 'POST', body }),
  reviewRule: (value: string, body: RuleReviewInput) =>
    request<RuleProposal>(`rules/${id(value)}/reviews`, { method: 'POST', body }),
  updateCase: (value: string, body: CasePatch) =>
    request<Case>(`cases/${id(value)}`, { method: 'PATCH', body }),
};
