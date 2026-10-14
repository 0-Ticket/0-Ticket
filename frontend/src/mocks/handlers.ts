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
    page(state.tickets, request, ['status', 'handling_type', 'min_priority']),
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
      steps: state.steps.filter(
        (item) => item.subject_type === 'ticket' && item.subject_id === params.id,
      ),
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
    return json({ ...metrics, from, to });
  }),
  http.post(route('tickets/:id/reviews'), async ({ request, params }) => {
    const ticket = state.tickets.find((item) => item.ticket_id === params.id);
    if (!ticket) return error('not_found');
    if (reviewed.has(`ticket:${params.id}`) || ticket.status !== 'awaiting_human')
      return error('conflict');
    const input = await body(request, ['reviewer', 'decision', 'reason']);
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
    const incident = state.incidents.find((item) => item.incident_id === params.id);
    if (!incident) return error('not_found');
    if (reviewed.has(`incident:${params.id}`)) return error('conflict');
    const input = await body(request, ['reviewer', 'decision', 'reject_type', 'comment']);
    if (
      !input ||
      !text(input.reviewer) ||
      (input.decision !== 'approve' && input.decision !== 'reject')
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
    const review: L2Review = {
      incident_id: incident.incident_id,
      reviewer: input.reviewer,
      decision: input.decision,
      reject_type: (rejectType ?? null) as L2Review['reject_type'],
      comment: typeof input.comment === 'string' ? input.comment : null,
      round:
        Math.max(
          0,
          ...state.l2_reviews
            .filter((item) => item.incident_id === params.id)
            .map((item) => item.round),
        ) + 1,
      created_at: Date.now(),
    };
    state.l2_reviews.push(review);
    reviewed.add(`incident:${params.id}`);
    return json(review);
  }),
  http.post(route('rules/:id/reviews'), async ({ request, params }) => {
    const rule = state.rules.find((item) => item.proposal_id === params.id);
    if (!rule) return error('not_found');
    if (rule.status !== 'draft') return error('conflict');
    const input = await body(request, ['reviewer', 'decision']);
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
