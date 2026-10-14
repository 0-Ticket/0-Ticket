import { http, HttpResponse } from 'msw';
import { expect, it, vi } from 'vitest';
import errors from '../../../tests/fixtures/frontend/api-errors.json';
import { server } from '../mocks/server';
import { api } from './endpoints';
import { ApiError, request } from './client';

async function expectUnhandledRequestBlocked() {
  const diagnostic = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    // A warning or a connection failure is not proof that MSW blocked the request.
    await expect(fetch('http://localhost/api/unhandled-review-regression')).rejects.toMatchObject({
      cause: {
        message: expect.stringMatching(/Cannot bypass a request when using the "error" strategy/),
      },
    });
  } finally {
    diagnostic.mockRestore();
  }
}

it('blocks an unhandled request using the actual test server configuration', async () => {
  await expectUnhandledRequestBlocked();
});

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
  await expectUnhandledRequestBlocked();
});

it('preserves cancellation rather than reporting an internal failure', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(request('tickets', { signal: controller.signal })).rejects.toMatchObject({
    name: 'AbortError',
  });
});

it.each([
  new DOMException('Body reading was cancelled', 'AbortError'),
  Object.assign(new Error('Body reading was cancelled'), { name: 'AbortError' }),
])('preserves the original body-read AbortError: $constructor.name', async (abortError) => {
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.error(abortError);
      },
    }),
  );
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
  try {
    // Fetch has resolved. The real Response.json() rejects while reading its body.
    await expect(request('tickets')).rejects.toBe(abortError);
  } finally {
    fetchSpy.mockRestore();
  }
});

it('converts a non-abort body read failure to ApiError', async () => {
  const response = new Response(
    new ReadableStream({
      start(controller) {
        controller.error(new TypeError('Body read failed'));
      },
    }),
    { status: 503 },
  );
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);
  try {
    const failure = request('tickets');
    await expect(failure).rejects.toBeInstanceOf(ApiError);
    await expect(failure).rejects.toMatchObject({
      code: 'internal',
      status: 503,
      message: 'API 응답을 읽을 수 없습니다.',
    });
  } finally {
    fetchSpy.mockRestore();
  }
});

it('converts invalid JSON in a successful HTTP response to ApiError', async () => {
  server.use(http.get('*/api/tickets', () => new HttpResponse('not JSON', { status: 200 })));
  await expect(api.tickets()).rejects.toMatchObject({
    name: 'ApiError',
    code: 'internal',
    status: 200,
  });
});
