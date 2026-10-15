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

it('records exactly one concurrent Incident review and advances its round only once', async () => {
  const before = await api.incident('in_sample');
  const winner = await race([
    () => api.reviewIncident('in_sample', { reviewer: 'demo-approve', decision: 'approve' }),
    () =>
      api.reviewIncident('in_sample', {
        reviewer: 'demo-reject',
        decision: 'reject',
        reject_type: 'missing_step',
        comment: 'Synthetic rejection',
      }),
  ]);
  const after = await api.incident('in_sample');
  expect(after.reviews).toEqual([...before.reviews, winner]);
  expect(winner.round).toBe(Math.max(0, ...before.reviews.map((review) => review.round)) + 1);
  // F0 stores the L2 decision; actual Incident lifecycle transitions belong to the core.
  expect(after.incident).toEqual(before.incident);
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
