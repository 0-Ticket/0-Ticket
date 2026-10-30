import { http, HttpResponse } from 'msw';
import { config } from '../config';
import type { CaseTask, HumanReview, L2Review } from '../contracts';
import type { ErrorCode } from '../api/types';
import errors from '../../../tests/fixtures/frontend/api-errors.json';
import { data, metrics } from './data';

let state = structuredClone(data);
const reviewed = new Set<string>();
export function resetMockState() {
  state = structuredClone(data);
  reviewed.clear();
}

const base = config.apiBaseUrl.replace(/\/$/, '');
const route = (path: string) => `${base.startsWith('/') ? '*' : ''}${base}/${path}`;
const json = HttpResponse.json;
const error = (code: ErrorCode) =>
  json(errors[code], {
    status: { not_found: 404, invalid_input: 400, conflict: 409, internal: 500 }[code],
  });
const text = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;
const oneOf = (value: unknown, values: string[]): value is string =>
  typeof value === 'string' && values.includes(value);
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

// C23 enum values (docs/data-contracts.md C23); the registered values stay unchecked.
const decisionFilters: Record<string, string[]> = {
  subject_type: ['alert', 'ticket'],
  decision: ['l1_escalated', 'held', 'closed_fp', 'l2_escalated'],
  reason: ['below_threshold', 'llm_failure', 'evidence_request_failure'],
};
// Newest first, as the L1 result read serves them.
const sortedDecisions = () => [...state.decisions].sort((a, b) => b.created_at - a.created_at);
const decisionsOf = (subject_type: string, subject_id: string) =>
  sortedDecisions().filter(
    (item) => item.subject_type === subject_type && item.subject_id === subject_id,
  );

function page<T extends object>(items: T[], request: Request, filters: string[]) {
  const query = new URL(request.url).searchParams;
  const limitText = query.get('limit') ?? '50';
  const cursorText = query.get('cursor') ?? '0';
  if (!/^\d+$/.test(limitText) || !/^\d+$/.test(cursorText)) return error('invalid_input');
  const limit = Number(limitText),
    cursor = Number(cursorText);
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 200 || !Number.isSafeInteger(cursor))
    return error('invalid_input');
  if (
    query.has('min_priority') &&
    (!text(query.get('min_priority')) || !Number.isFinite(Number(query.get('min_priority'))))
  )
    return error('invalid_input');
  if (query.has('is_anomaly') && !['true', 'false'].includes(query.get('is_anomaly')!))
    return error('invalid_input');
  const filtered = items.filter((item) =>
    filters.every((key) => {
      const value = query.get(key);
      if (value === null) return true;
      const row = item as Record<string, unknown>;
      return key === 'min_priority'
        ? Number(row.priority) >= Number(value)
        : String(row[key]) === value;
    }),
  );
  return json({
    items: filtered.slice(cursor, cursor + limit),
    next_cursor: cursor + limit < filtered.length ? String(cursor + limit) : null,
  });
}

async function body(request: Request, allowed: string[]) {
  try {
    const value: unknown = await request.json();
    return object(value) && Object.keys(value).every((key) => allowed.includes(key)) ? value : null;
  } catch {
    return null;
  }
}

function validTasks(tasks: unknown): tasks is CaseTask[] {
  return (
    Array.isArray(tasks) &&
    tasks.every(
      (task) =>
        object(task) &&
        Object.keys(task).length === 4 &&
        typeof task.task === 'string' &&
        typeof task.owner === 'string' &&
        (task.due_at === null || Number.isSafeInteger(task.due_at)) &&
        oneOf(task.status, ['todo', 'doing', 'done']),
    )
  );
}

// This is a deterministic in-memory development simulation, not core validation
// or a persistent backend. The actual API must delegate validation to the core.
export const handlers = [
  http.get(route('tickets'), ({ request }) =>
    page(
      [...state.tickets].sort(
        (a, b) =>
          b.priority - a.priority ||
          a.created_at - b.created_at ||
          (a.ticket_id < b.ticket_id ? -1 : a.ticket_id > b.ticket_id ? 1 : 0),
      ),
      request,
      ['status', 'origin', 'handling_type', 'min_priority'],
    ),
  ),
  http.get(route('incidents'), ({ request }) =>
    page(state.incidents, request, ['status', 'created_by']),
  ),
  http.get(route('cases'), ({ request }) => page(state.cases, request, ['status'])),
  http.get(route('hunts'), ({ request }) => page(state.hunts, request, ['is_anomaly'])),
  http.get(route('rules'), ({ request }) => page(state.rules, request, ['status'])),
  http.get(route('normalize-failures'), ({ request }) =>
    page(state.normalize_failures, request, ['reason']),
  ),
  http.get(route('tickets/:id'), ({ params }) => {
    const ticket = state.tickets.find((item) => item.ticket_id === params.id);
    if (!ticket) return error('not_found');
    return json({
      ticket,
      alerts: state.alerts.filter((item) => ticket.alert_ids.includes(item.alert_id)),
      findings: state.findings.filter((item) => item.ticket_id === params.id),
      decisions: decisionsOf('ticket', String(params.id)),
      evidence_requests: state.evidence_requests.filter(
        (item) => item.requester_type === 'ticket' && item.requester_id === params.id,
      ),
      // Ticket steps and the steps of its alerts, in time order (docs/api-contracts.md).
      steps: state.steps
        .filter(
          (item) =>
            (item.subject_type === 'ticket' && item.subject_id === params.id) ||
            (item.subject_type === 'alert' && ticket.alert_ids.includes(item.subject_id)),
        )
        .sort((a, b) => a.created_at - b.created_at),
      reviews: state.reviews.filter((item) => item.ticket_id === params.id),
      incident_ids: state.incidents
        .filter((item) => item.members.some((member) => member.ticket_id === params.id))
        .map((item) => item.incident_id),
    });
  }),
  http.get(route('alerts/:id'), ({ params }) => {
    const item = state.alerts.find((item) => item.alert_id === params.id);
    return item ? json(item) : error('not_found');
  }),
  http.get(route('alerts/:id/l1'), ({ params }) => {
    const alert = state.alerts.find((item) => item.alert_id === params.id);
    if (!alert) return error('not_found');
    return json({
      alert,
      // No branch or decision yet is an empty result, not an error.
      branch:
        state.branches.find(
          (item) => item.subject_type === 'alert' && item.subject_id === params.id,
        ) ?? null,
      decisions: decisionsOf('alert', String(params.id)),
      evidence_requests: state.evidence_requests.filter(
        (item) => item.requester_type === 'alert' && item.requester_id === params.id,
      ),
      steps: state.steps.filter(
        (item) => item.subject_type === 'alert' && item.subject_id === params.id,
      ),
    });
  }),
  http.get(route('l1/decisions'), ({ request }) => {
    const query = new URL(request.url).searchParams;
    // C23 enum filters, like the real API: an unknown value is invalid_input, not an empty page.
    for (const [key, values] of Object.entries(decisionFilters)) {
      const value = query.get(key);
      if (value !== null && !values.includes(value)) return error('invalid_input');
    }
    return page(sortedDecisions(), request, ['subject_type', 'decision', 'reason']);
  }),
  http.get(route('events/:id'), ({ params }) => {
    const item = state.events.find((item) => item.event_id === params.id);
    return item ? json(item) : error('not_found');
  }),
  http.get(route('raw/:id'), ({ params }) => {
    const item = state.raw.find((item) => item.raw_id === params.id);
    return item ? json(item) : error('not_found');
  }),
  http.get(route('incidents/:id'), ({ params }) => {
    const incident = state.incidents.find((item) => item.incident_id === params.id);
    if (!incident) return error('not_found');
    return json({
      incident,
      tickets: state.tickets.filter((item) =>
        incident.members.some((member) => member.ticket_id === item.ticket_id),
      ),
      hunts: state.hunts.filter((item) =>
        incident.members.some((member) => member.hunt_id === item.hunt_id),
      ),
      artifact: state.artifacts.find((item) => item.incident_id === params.id) ?? null,
      steps: state.steps.filter(
        (item) => item.subject_type === 'incident' && item.subject_id === params.id,
      ),
      reviews: state.l2_reviews.filter((item) => item.incident_id === params.id),
      case_id: state.cases.find((item) => item.incident_id === params.id)?.case_id ?? null,
    });
  }),
  http.get(route('cases/:id'), ({ params }) => {
    const item = state.cases.find((item) => item.case_id === params.id);
    return item
      ? json({
          case: item,
          proposal_ids: state.rules
            .filter((rule) => rule.case_id === params.id)
            .map((rule) => rule.proposal_id),
        })
      : error('not_found');
  }),
  http.get(route('hunts/:id'), ({ params }) => {
    const hunt = state.hunts.find((item) => item.hunt_id === params.id);
    return hunt
      ? json({
          hunt,
          steps: state.steps.filter(
            (item) => item.subject_type === 'hunt' && item.subject_id === params.id,
          ),
          proposal_ids: state.rules
            .filter((item) => item.hunt_id === params.id)
            .map((item) => item.proposal_id),
        })
      : error('not_found');
  }),
  http.get(route('rules/:id'), ({ params }) => {
    const item = state.rules.find((item) => item.proposal_id === params.id);
    return item ? json(item) : error('not_found');
  }),
  http.get(route('metrics'), ({ request }) => {
    const query = new URL(request.url).searchParams;
    const from = Number(query.get('from')),
      to = Number(query.get('to'));
    if (
      !text(query.get('from')) ||
      !text(query.get('to')) ||
      !Number.isSafeInteger(from) ||
      !Number.isSafeInteger(to) ||
      from > to
    )
      return error('invalid_input');
    return json({
      ...metrics,
      from,
      to,
      tickets_awaiting_human: state.tickets.filter((ticket) => ticket.status === 'awaiting_human')
        .length,
    });
  }),
  http.post(route('tickets/:id/reviews'), async ({ request, params }) => {
    // Finish asynchronous work before reading current state. Keep the checks and
    // mutation below in one synchronous turn; existing error precedence is retained.
    const input = await body(request, ['reviewer', 'decision', 'reason']);
    const ticket = state.tickets.find((item) => item.ticket_id === params.id);
    if (!ticket) return error('not_found');
    if (reviewed.has(`ticket:${params.id}`) || ticket.status !== 'awaiting_human')
      return error('conflict');
    if (!input || !text(input.reviewer) || (input.decision !== 'tp' && input.decision !== 'fp'))
      return error('invalid_input');
    const overturned = input.decision !== ticket.verdict?.verdict;
    if (
      (overturned && !text(input.reason)) ||
      (input.reason != null && typeof input.reason !== 'string')
    )
      return error('invalid_input');
    const review: HumanReview = {
      ticket_id: ticket.ticket_id,
      reviewer: input.reviewer,
      decision: input.decision,
      overturned,
      reason: typeof input.reason === 'string' ? input.reason : null,
      created_at: Date.now(),
    };
    state.reviews.push(review);
    ticket.status = input.decision === 'tp' ? 'escalated' : 'closed_fp';
    ticket.updated_at = review.created_at;
    reviewed.add(`ticket:${params.id}`);
    return json(review);
  }),
  http.post(route('incidents/:id/reviews'), async ({ request, params }) => {
    // No await between the current-state check and recording this review, so exactly one
    // request wins each review opportunity.
    const input = await body(request, [
      'reviewer',
      'decision',
      'reject_type',
      'comment',
      'expected_review_round',
    ]);
    const incident = state.incidents.find((item) => item.incident_id === params.id);
    if (!incident) return error('not_found');
    // C10 review_state/review_round are the only source of review availability (#21).
    if (incident.review_state !== 'awaiting_review' || incident.review_round === null)
      return error('conflict');
    if (
      !input ||
      !text(input.reviewer) ||
      (input.decision !== 'approve' && input.decision !== 'reject') ||
      !Number.isSafeInteger(input.expected_review_round)
    )
      return error('invalid_input');
    const rejectType = input.reject_type;
    if (
      rejectType != null &&
      !oneOf(rejectType, ['wrong_grouping', 'missing_step', 'wrong_conclusion'])
    )
      return error('invalid_input');
    if (input.comment != null && typeof input.comment !== 'string') return error('invalid_input');
    if (input.decision === 'reject' && (!rejectType || !text(input.comment)))
      return error('invalid_input');
    // A stale screen answering an earlier or later opportunity must not be recorded.
    if (input.expected_review_round !== incident.review_round) return error('conflict');
    const review: L2Review = {
      incident_id: incident.incident_id,
      reviewer: input.reviewer,
      decision: input.decision,
      reject_type: (rejectType ?? null) as L2Review['reject_type'],
      comment: typeof input.comment === 'string' ? input.comment : null,
      round: incident.review_round,
      created_at: Date.now(),
    };
    state.l2_reviews.push(review);
    // Box 36 flow: approve ends the loop, the first rejection returns to L2 analysis and the
    // second hands the Incident to a person. Lifecycle status and Case creation are not
    // changed here (box 37); the mock never reanalyzes, so new rounds come from fixtures.
    const rejects = state.l2_reviews.filter(
      (item) => item.incident_id === incident.incident_id && item.decision === 'reject',
    ).length;
    incident.review_state =
      input.decision === 'approve' ? 'approved' : rejects >= 2 ? 'human_handling' : 'analyzing';
    incident.review_round = null;
    return json(review);
  }),
  http.post(route('rules/:id/reviews'), async ({ request, params }) => {
    // No await between checking draft status and applying the winning decision.
    const input = await body(request, ['reviewer', 'decision']);
    const rule = state.rules.find((item) => item.proposal_id === params.id);
    if (!rule) return error('not_found');
    if (rule.status !== 'draft') return error('conflict');
    if (
      !input ||
      !text(input.reviewer) ||
      (input.decision !== 'approve' && input.decision !== 'reject')
    )
      return error('invalid_input');
    rule.status = input.decision === 'approve' ? 'approved' : 'rejected';
    rule.reviewer = input.reviewer;
    return json(rule);
  }),
  http.patch(route('cases/:id'), async ({ request, params }) => {
    const item = state.cases.find((item) => item.case_id === params.id);
    if (!item) return error('not_found');
    const input = await body(request, ['status', 'tasks', 'lessons']);
    if (!input || !Object.keys(input).length) return error('invalid_input');
    if ('status' in input && !oneOf(input.status, ['open', 'responding', 'closed']))
      return error('invalid_input');
    if ('tasks' in input && !validTasks(input.tasks)) return error('invalid_input');
    if ('lessons' in input && input.lessons !== null && typeof input.lessons !== 'string')
      return error('invalid_input');
    Object.assign(item, input);
    if ('status' in input) item.closed_at = input.status === 'closed' ? Date.now() : null;
    return json(item);
  }),
];
