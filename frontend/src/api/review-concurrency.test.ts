import { expect, it, vi } from 'vitest';
import { api } from './endpoints';
import { ApiError } from './client';

// Hold both HTTP bodies at the same asynchronous boundary. No sleeps or assumed
// winner: both requests must reach body parsing before either may finish it.
async function race<T>(send: Array<() => Promise<T>>) {
  const original = Request.prototype.json;
  let arrived = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const parse = vi.spyOn(Request.prototype, 'json').mockImplementation(async function (
    this: Request,
  ) {
    const value: unknown = await original.call(this);
    if (this.method === 'POST' && new URL(this.url).pathname.endsWith('/reviews')) {
      arrived += 1;
      if (arrived === 2) release();
      await gate;
    }
    return value;
  });
  try {
    const results = await Promise.allSettled(send.map((request) => request()));
    expect(arrived).toBe(2);
    const successes = results.filter((result) => result.status === 'fulfilled');
    const failures = results.filter((result) => result.status === 'rejected');
    expect(successes).toHaveLength(1);
    expect(failures).toHaveLength(1);
    expect(failures[0].reason).toBeInstanceOf(ApiError);
    expect(failures[0].reason).toMatchObject({ code: 'conflict', status: 409 });
    return successes[0].value;
  } finally {
    parse.mockRestore();
  }
}

it('records exactly one concurrent Ticket review and preserves the winning decision', async () => {
  const before = await api.ticket('tk_sample');
  const winner = await race([
    () =>
      api.reviewTicket('tk_sample', {
        reviewer: 'demo-tp',
        decision: 'tp',
        reason: 'Synthetic TP',
      }),
    () =>
      api.reviewTicket('tk_sample', {
        reviewer: 'demo-fp',
        decision: 'fp',
        reason: 'Synthetic FP',
      }),
  ]);
  const after = await api.ticket('tk_sample');
  expect(after.reviews).toEqual([...before.reviews, winner]);
  expect(after.ticket.status).toBe(winner.decision === 'tp' ? 'escalated' : 'closed_fp');
  expect(after.ticket.updated_at).toBe(winner.created_at);
});

it('records exactly one concurrent review for the same Incident review opportunity', async () => {
  const before = await api.incident('in_second_round');
  const winner = await race([
    () =>
      api.reviewIncident('in_second_round', {
        reviewer: 'demo-approve',
        decision: 'approve',
        expected_review_round: 2,
      }),
    () =>
      api.reviewIncident('in_second_round', {
        reviewer: 'demo-reject',
        decision: 'reject',
        reject_type: 'missing_step',
        comment: 'Synthetic rejection',
        expected_review_round: 2,
      }),
  ]);
  const after = await api.incident('in_second_round');
  expect(after.reviews).toEqual([...before.reviews, winner]);
  // The round is the opportunity the server had open, not a count of past reviews.
  expect(winner.round).toBe(before.incident.review_round);
  // Only the review workflow moves; the lifecycle status belongs to the core lifecycle.
  expect(after.incident).toEqual({
    ...before.incident,
    review_state: winner.decision === 'approve' ? 'approved' : 'human_handling',
    review_round: null,
  });
});

it('applies exactly one concurrent Rule review without overwriting its reviewer or status', async () => {
  const before = await api.rules();
  const winner = await race([
    () => api.reviewRule('rp_sample', { reviewer: 'demo-approve', decision: 'approve' }),
    () => api.reviewRule('rp_sample', { reviewer: 'demo-reject', decision: 'reject' }),
  ]);
  expect(await api.rule('rp_sample')).toEqual(winner);
  expect(winner.status).toBe(winner.reviewer === 'demo-approve' ? 'approved' : 'rejected');
  const after = await api.rules();
  expect(after.items).toHaveLength(before.items.length);
  expect(after.items.filter((rule) => rule.proposal_id === 'rp_sample')).toEqual([winner]);
});
