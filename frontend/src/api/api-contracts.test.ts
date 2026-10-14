import { describe, expect, it } from 'vitest';
import { api } from './endpoints';
import { data } from '../mocks/data';
import { request } from './client';

describe('documented API contracts', () => {
  it('rejects non-string enum values instead of coercing them into contract outputs', async () => {
    await expect(
      request('incidents/in_sample/reviews', {
        method: 'POST',
        body: {
          reviewer: 'demo',
          decision: 'reject',
          reject_type: ['missing_step'],
          comment: 'Synthetic',
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
      next_cursor: null,
    });
    expect((await api.tickets({ limit: 200 })).items).toHaveLength(3);
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
    expect((await api.incidents({ created_by: 'manual' })).items).toEqual([]);
    expect((await api.cases({ status: 'closed' })).items).toEqual([]);
    expect((await api.rules({ status: 'deployed' })).items).toEqual([]);
    expect((await api.normalizeFailures({ reason: 'unknown_scenario' })).items).toEqual([]);
  });

  it('serves every documented read endpoint with its documented envelope', async () => {
    expect(await api.ticket('tk_sample')).toEqual({
      ticket: data.tickets[0],
      alerts: [data.alerts[0]],
      findings: data.findings,
      steps: data.steps,
      reviews: data.reviews,
      incident_ids: ['in_sample'],
    });
    expect(await api.alert('al_sample')).toEqual(data.alerts[0]);
    expect(await api.event('ev_sample')).toEqual(data.events[0]);
    expect(await api.raw('raw_sample_1')).toEqual(data.raw[0]);
    expect((await api.incidents()).items).toEqual(data.incidents);
    expect(await api.incident('in_sample')).toEqual({
      incident: data.incidents[0],
      tickets: [data.tickets[0]],
      hunts: data.hunts,
      artifact: data.artifacts[0],
      steps: [],
      reviews: data.l2_reviews,
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
      await api.reviewIncident('in_sample', {
        reviewer: 'demo',
        decision: 'reject',
        reject_type: 'missing_step',
        comment: 'Synthetic review',
      }),
    ).toMatchObject({ decision: 'reject', round: 2 });
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
      api.reviewIncident('in_sample', { reviewer: 'demo', decision: 'approve' }),
    ).rejects.toMatchObject({ code: 'conflict' });
  });

  it('rejects incomplete reviews, unknown objects and invalid case patches', async () => {
    await expect(
      api.reviewTicket('tk_sample', { reviewer: 'demo', decision: 'fp' }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      api.reviewIncident('in_sample', { reviewer: 'demo', decision: 'reject' }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
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
      request('incidents/in_sample/reviews', {
        method: 'POST',
        body: { reviewer: 'demo', decision: 'approve', round: 99 },
      }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
    await expect(
      request('cases/cs_sample', { method: 'PATCH', body: { execute: 'anything' } }),
    ).rejects.toMatchObject({ code: 'invalid_input' });
  });
});
