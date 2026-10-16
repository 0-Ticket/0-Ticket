import { describe, expect, it } from 'vitest';
import { api } from './endpoints';
import { data } from '../mocks/data';
import { request } from './client';

describe('documented API contracts', () => {
  it('rejects non-string enum values instead of coercing them into contract outputs', async () => {
    await expect(
      request('incidents/in_web_campaign/reviews', {
        method: 'POST',
        body: {
          reviewer: 'demo',
          decision: 'reject',
          reject_type: ['missing_step'],
          comment: 'Synthetic',
          expected_review_round: 1,
        },
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      request('cases/cs_sample', { method: 'PATCH', body: { status: ['closed'] } }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      request('cases/cs_sample', {
        method: 'PATCH',
        body: { tasks: [{ task: 'Review', owner: 'demo', due_at: null, status: ['done'] }] },
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
  });
  it('filters and paginates tickets without changing contract objects', async () => {
    const first = await api.tickets({ status: 'awaiting_human', limit: 1 });
    expect(first).toEqual({ items: [data.tickets[0]], next_cursor: '1' });
    const next = await api.tickets({ cursor: first.next_cursor!, limit: 1 });
    expect(next.items[0].ticket_id).toBe('tk_cloud');
    expect(await api.tickets({ cursor: '2', limit: 1 })).toEqual({
      items: [data.tickets[2]],
      next_cursor: '3',
    });
    expect((await api.tickets({ limit: 200 })).items).toHaveLength(6);
    expect(await api.tickets({ handling_type: 'missing' })).toEqual({
      items: [],
      next_cursor: null,
    });
    expect((await api.tickets({ min_priority: 15 })).items).toHaveLength(1);
    await expect(api.tickets({ limit: 201 })).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(api.tickets({ cursor: 'invalid' })).rejects.toMatchObject({
      code: 'invalid_input',
    });
  });

  it('preserves unknown registered values and extensions, and handles empty filtered lists', async () => {
    expect((await api.ticket('tk_custom')).ticket).toEqual(data.tickets[2]);
    expect((await api.hunts({ is_anomaly: false })).items).toEqual([]);
    expect(
      (await api.incidents({ status: 'escalated_to_case', created_by: 'manual' })).items,
    ).toEqual([]);
    // F4 fixtures cover every Case status, so the status filter is checked against the data.
    expect((await api.cases({ status: 'closed' })).items).toEqual(
      data.cases.filter((item) => item.status === 'closed'),
    );
    expect((await api.rules({ status: 'deployed' })).items).toEqual([]);
    expect((await api.normalizeFailures({ reason: 'unknown_scenario' })).items).toEqual([]);
  });

  it('serves every documented read endpoint with its documented envelope', async () => {
    expect(await api.ticket('tk_sample')).toEqual({
      ticket: data.tickets[0],
      alerts: [data.alerts[0]],
      findings: data.findings,
      steps: data.steps.filter((step) => step.subject_id === 'tk_sample'),
      reviews: data.reviews,
      incident_ids: ['in_sample', 'in_web_campaign'],
    });
    expect(await api.alert('al_sample')).toEqual(data.alerts[0]);
    expect(await api.event('ev_sample')).toEqual(data.events[0]);
    expect(await api.raw('raw_sample_1')).toEqual(data.raw[0]);
    expect((await api.incidents()).items).toEqual(data.incidents);
    expect(await api.incident('in_sample')).toEqual({
      incident: data.incidents[0],
      tickets: [data.tickets[0]],
      hunts: [data.hunts[0]],
      artifact: data.artifacts[0],
      steps: [],
      reviews: data.l2_reviews.filter((review) => review.incident_id === 'in_sample'),
      case_id: 'cs_sample',
    });
    expect((await api.cases()).items).toEqual(data.cases);
    expect(await api.case('cs_sample')).toEqual({ case: data.cases[0], proposal_ids: [] });
    expect((await api.hunts({ is_anomaly: true })).items).toEqual(data.hunts);
    expect(await api.hunt('ht_sample')).toEqual({
      hunt: data.hunts[0],
      steps: [],
      proposal_ids: ['rp_sample'],
    });
    expect((await api.rules()).items).toEqual(data.rules);
    expect(await api.rule('rp_sample')).toEqual(data.rules[0]);
    expect((await api.normalizeFailures()).items).toEqual(data.normalize_failures);
    expect(await api.metrics({ from: 1, to: 2 })).toMatchObject({
      from: 1,
      to: 2,
      tickets_total: 3,
    });
  });

  it('accepts documented writes and returns contract objects without deploying rules', async () => {
    expect(
      await api.reviewTicket('tk_sample', {
        reviewer: 'demo',
        decision: 'tp',
        reason: 'Synthetic review',
      }),
    ).toMatchObject({ ticket_id: 'tk_sample', overturned: true });
    await expect(
      api.reviewTicket('tk_sample', { reviewer: 'demo', decision: 'tp' }),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect(
      await api.reviewIncident('in_web_campaign', {
        reviewer: 'demo',
        decision: 'reject',
        reject_type: 'missing_step',
        comment: 'Synthetic review',
        expected_review_round: 1,
      }),
    ).toMatchObject({ decision: 'reject', round: 1 });
    expect(
      await api.reviewRule('rp_sample', { reviewer: 'demo', decision: 'approve' }),
    ).toMatchObject({ status: 'approved' });
    expect(await api.updateCase('cs_sample', { lessons: 'Synthetic lesson' })).toMatchObject({
      lessons: 'Synthetic lesson',
    });
    expect((await api.ticket('tk_sample')).ticket.status).toBe('escalated');
    expect((await api.rule('rp_sample')).status).toBe('approved');
    expect((await api.case('cs_sample')).case.lessons).toBe('Synthetic lesson');
    await expect(
      api.reviewRule('rp_sample', { reviewer: 'demo', decision: 'approve' }),
    ).rejects.toMatchObject({ code: 'conflict' });
    await expect(
      api.reviewIncident('in_web_campaign', {
        reviewer: 'demo',
        decision: 'approve',
        expected_review_round: 1,
      }),
    ).rejects.toMatchObject({ code: 'conflict' });
  });

  it.each([
    ['in_sample', 'approved'],
    ['in_escalated', 'approved'],
    ['in_reanalysis', 'analyzing'],
    ['in_manual', 'human_handling'],
    ['in_benign', 'human_handling'],
  ])('returns conflict for %s (review_state %s) without recording a review', async (id, state) => {
    const before = await api.incident(id);
    expect(before.incident.review_state).toBe(state);
    expect(before.incident.review_round).toBeNull();
    for (const body of [
      { reviewer: 'demo', decision: 'approve' as const, expected_review_round: 1 },
      {
        reviewer: 'demo',
        decision: 'reject' as const,
        reject_type: 'missing_step' as const,
        comment: 'Synthetic',
        expected_review_round: 2,
      },
    ])
      await expect(api.reviewIncident(id, body)).rejects.toMatchObject({ code: 'conflict' });
    expect(await api.incident(id)).toEqual(before);
  });

  it('opens review only for the current opportunity and records the server round', async () => {
    const before = await api.incident('in_second_round');
    expect(before.incident).toMatchObject({ review_state: 'awaiting_review', review_round: 2 });
    for (const expected of [1, 3])
      await expect(
        api.reviewIncident('in_second_round', {
          reviewer: 'demo',
          decision: 'approve',
          expected_review_round: expected,
        }),
      ).rejects.toMatchObject({ code: 'conflict' });
    expect(await api.incident('in_second_round')).toEqual(before);
    const review = await api.reviewIncident('in_second_round', {
      reviewer: 'demo',
      decision: 'approve',
      expected_review_round: 2,
    });
    expect(review).toMatchObject({ decision: 'approve', round: 2 });
    const after = await api.incident('in_second_round');
    expect(after.reviews).toEqual([...before.reviews, review]);
    // Lifecycle status is untouched; Case creation belongs to box 22.
    expect(after.incident).toEqual({
      ...before.incident,
      review_state: 'approved',
      review_round: null,
    });
    expect(after.case_id).toBeNull();
    await expect(
      api.reviewIncident('in_second_round', {
        reviewer: 'demo',
        decision: 'approve',
        expected_review_round: 2,
      }),
    ).rejects.toMatchObject({ code: 'conflict' });
  });

  it('applies the documented L2 error precedence', async () => {
    const post = (id: string, body: Record<string, unknown>) =>
      request(`incidents/${id}/reviews`, { method: 'POST', body });
    // 1. not_found wins over every body problem.
    await expect(post('in_missing', { decision: 'maybe' })).rejects.toMatchObject({
      code: 'not_found',
    });
    // 2. A closed review workflow is a conflict even when the body is malformed.
    await expect(post('in_manual', { decision: 'maybe' })).rejects.toMatchObject({
      code: 'conflict',
    });
    await expect(
      post('in_reanalysis', { reviewer: 'demo', decision: 'approve' }),
    ).rejects.toMatchObject({ code: 'conflict' });
    // 3. On an open opportunity, body errors come before the round check.
    await expect(
      post('in_second_round', { reviewer: 'demo', decision: 'reject', expected_review_round: 1 }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      post('in_second_round', { reviewer: 'demo', decision: 'approve' }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    // 4. A well-formed body for another round is a conflict.
    await expect(
      post('in_second_round', { reviewer: 'demo', decision: 'approve', expected_review_round: 1 }),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect((await api.incident('in_second_round')).incident.review_round).toBe(2);
  });

  it('rejects a stale tab that still holds an answered round', async () => {
    // Tabs A and B both loaded round 1.
    const seen = (await api.incident('in_web_campaign')).incident.review_round!;
    const a = await api.reviewIncident('in_web_campaign', {
      reviewer: 'tab-a',
      decision: 'reject',
      reject_type: 'missing_step',
      comment: 'Synthetic rejection',
      expected_review_round: seen,
    });
    expect(a.round).toBe(1);
    const before = await api.incident('in_web_campaign');
    await expect(
      api.reviewIncident('in_web_campaign', {
        reviewer: 'tab-b',
        decision: 'approve',
        expected_review_round: seen,
      }),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect(await api.incident('in_web_campaign')).toEqual(before);
    // After reanalysis opens a later round, an old round is still refused (fixture round 2).
    await expect(
      api.reviewIncident('in_second_round', {
        reviewer: 'tab-b',
        decision: 'approve',
        expected_review_round: 1,
      }),
    ).rejects.toMatchObject({ code: 'conflict' });
    expect((await api.incident('in_second_round')).incident).toMatchObject({
      review_state: 'awaiting_review',
      review_round: 2,
    });
  });

  it('moves a first rejection to analyzing and a second rejection to human handling', async () => {
    const reject = (id: string, round: number) =>
      api.reviewIncident(id, {
        reviewer: 'demo',
        decision: 'reject',
        reject_type: 'wrong_conclusion',
        comment: 'Synthetic rejection',
        expected_review_round: round,
      });
    expect(await reject('in_web_campaign', 1)).toMatchObject({ round: 1 });
    expect((await api.incident('in_web_campaign')).incident).toMatchObject({
      status: 'investigating',
      review_state: 'analyzing',
      review_round: null,
    });
    expect(await reject('in_second_round', 2)).toMatchObject({ round: 2 });
    expect((await api.incident('in_second_round')).incident).toMatchObject({
      status: 'investigating',
      review_state: 'human_handling',
      review_round: null,
    });
    await expect(reject('in_second_round', 2)).rejects.toMatchObject({ code: 'conflict' });
    await expect(reject('in_second_round', 3)).rejects.toMatchObject({ code: 'conflict' });
  });

  it('rejects incomplete reviews, unknown objects and invalid case patches', async () => {
    await expect(
      api.reviewTicket('tk_sample', { reviewer: 'demo', decision: 'fp' }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      api.reviewIncident('in_web_campaign', {
        reviewer: 'demo',
        decision: 'reject',
        expected_review_round: 1,
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    for (const expected of [undefined, null, '1', 1.5])
      await expect(
        request('incidents/in_web_campaign/reviews', {
          method: 'POST',
          body: { reviewer: 'demo', decision: 'approve', expected_review_round: expected },
        }),
      ).rejects.toMatchObject({ code: 'invalid_input' });
    expect((await api.incident('in_web_campaign')).reviews).toEqual([]);
    await expect(api.ticket('tk_missing')).rejects.toMatchObject({ code: 'not_found' });
    await expect(api.updateCase('cs_sample', { status: 'invalid' as never })).rejects.toMatchObject(
      { code: 'invalid_input' },
    );
  });

  it('does not accept client-computed review fields or undocumented write keys', async () => {
    await expect(
      request('tickets/tk_sample/reviews', {
        method: 'POST',
        body: { reviewer: 'demo', decision: 'tp', reason: 'test', overturned: false },
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      request('incidents/in_web_campaign/reviews', {
        method: 'POST',
        body: { reviewer: 'demo', decision: 'approve', expected_review_round: 1, round: 1 },
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      request('cases/cs_sample', { method: 'PATCH', body: { execute: 'anything' } }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
  });
});

it('orders every cursor page by priority DESC, created_at ASC, ticket_id ASC', async () => {
  const ids: string[] = [];
  let cursor: string | undefined;
  do {
    const page = await api.tickets({ limit: 1, cursor });
    ids.push(...page.items.map((ticket) => ticket.ticket_id));
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  expect(ids).toEqual(['tk_sample', 'tk_cloud', 'tk_custom', 'tk_tie_a', 'tk_tie_z', 'tk_later']);
  expect(new Set(ids).size).toBe(data.tickets.length);
});

it('keeps detail review history and waiting timestamp consistent with refreshed list and metrics', async () => {
  const before = await api.ticket('tk_sample');
  const metricBefore = await api.metrics({ from: 0, to: Date.now() });
  const review = await api.reviewTicket('tk_sample', {
    reviewer: 'f2-reviewer',
    decision: 'fp',
    reason: 'Synthetic review',
  });
  const after = await api.ticket('tk_sample');
  const waiting = await api.tickets({ status: 'awaiting_human' });
  const all = await api.tickets();
  const metricAfter = await api.metrics({ from: 0, to: Date.now() });
  expect(after.reviews).toEqual([...before.reviews, review]);
  expect(after.ticket.awaiting_human_at).toBe(before.ticket.awaiting_human_at);
  expect(waiting.items.some((ticket) => ticket.ticket_id === 'tk_sample')).toBe(false);
  expect(all.items.find((ticket) => ticket.ticket_id === 'tk_sample')).toEqual(after.ticket);
  expect(metricAfter.tickets_awaiting_human).toBe(metricBefore.tickets_awaiting_human - 1);
});
