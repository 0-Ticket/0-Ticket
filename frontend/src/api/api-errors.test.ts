import { http, HttpResponse } from 'msw';
import { expect, it, vi } from 'vitest';
import errors from '../../../tests/fixtures/frontend/api-errors.json';
import { server } from '../mocks/server';
import { api } from './endpoints';
import { request } from './client';

it.each(Object.entries(errors))('preserves the %s API error', async (code, body) => {
  server.use(http.get('*/api/tickets', () => HttpResponse.json(body, { status: 400 })));
  await expect(api.tickets()).rejects.toMatchObject({ code, message: body.error.message });
});

it('handles non-JSON failures and network errors', async () => {
  server.use(
    http.get('*/api/tickets', () => new HttpResponse('<html>failure</html>', { status: 502 })),
  );
  await expect(api.tickets()).rejects.toMatchObject({ code: 'internal' });
  server.use(http.get('*/api/tickets', () => HttpResponse.error()));
  await expect(api.tickets()).rejects.toMatchObject({ code: 'internal' });
});

it('uses the same API client without MSW and serializes only documented review inputs', async () => {
  server.close();
  const fetchSpy = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(Response.json({ ticket_id: 'tk_demo' }));
  try {
    await api.reviewTicket('tk_demo', { reviewer: 'demo', decision: 'fp', reason: 'Synthetic' });
    const [url, options] = fetchSpy.mock.calls[0];
    expect(String(url)).toBe('http://localhost/api/tickets/tk_demo/reviews');
    expect(options?.method).toBe('POST');
    expect(JSON.parse(String(options?.body))).toEqual({
      reviewer: 'demo',
      decision: 'fp',
      reason: 'Synthetic',
    });
    expect(options?.headers).toMatchObject({ 'Content-Type': 'application/json' });
  } finally {
    fetchSpy.mockRestore();
    server.listen({ onUnhandledFrame: 'error' });
  }
});

it('preserves cancellation rather than reporting an internal failure', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(request('tickets', { signal: controller.signal })).rejects.toMatchObject({
    name: 'AbortError',
  });
});
