import { createTestQueryClient } from '../test/query-clients';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it, vi } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import { data } from '../mocks/data';
import untrusted from '../../../tests/fixtures/frontend/untrusted-text.json';

function mount(path = '/tickets', interval = false as number | false) {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: interval, staleTime: 1000 } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
  return { ...view, client };
}

it('renders server order, shared lookup cache, safe values and detail links without review controls', async () => {
  let alerts = 0;
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ items: [data.tickets[2], data.tickets[0]], next_cursor: null }),
    ),
    http.get('*/api/alerts/:id', () => {
      alerts++;
      return HttpResponse.json(data.alerts[0]);
    }),
  );
  mount();
  // First MSW -> Query -> render of this page exceeded the 1s default under heavy CPU load.
  await screen.findByText('tk_custom', { selector: 'a' }, { timeout: 3000 });
  const links = screen.getAllByRole('link', { name: /^tk_/ });
  expect(links.map((link) => link.textContent)).toEqual(['tk_custom', 'tk_sample']);
  expect(links[0]).toHaveAttribute('href', '/tickets/tk_custom');
  expect(await screen.findAllByText('web-01')).toHaveLength(2);
  expect(alerts).toBe(1);
  expect(screen.getByText(/example\.custom/)).toBeInTheDocument();
  expect(screen.getByText(/example\.specialist/)).toBeInTheDocument();
  expect(screen.getAllByText('자산 정보 없음').length).toBeGreaterThan(0);
  expect(screen.getAllByText('없음').length).toBeGreaterThan(0);
  expect(screen.getAllByTitle(String(data.tickets[0].created_at)).length).toBeGreaterThan(0);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByText('뒤집기')).not.toBeInTheDocument();
});

it('renders attacker and LLM strings as plain text, including nested extensions', async () => {
  const ticket = structuredClone(data.tickets[0]);
  ticket.verdict!.summary = untrusted.summary;
  ticket.extensions = { ...untrusted.extensions, 'example.nested': { value: untrusted.payload } };
  server.use(
    http.get('*/api/tickets', () => HttpResponse.json({ items: [ticket], next_cursor: null })),
  );
  const { container } = mount();
  expect(await screen.findByText(untrusted.summary)).toBeInTheDocument();
  expect(screen.getByText(untrusted.extensions['example.note'])).toBeInTheDocument();
  expect(screen.getByText(/window.compromised/)).toBeInTheDocument();
  expect(container.querySelector('script, img, iframe')).toBeNull();
  expect(container.querySelector('a[href^="https://example.com"]')).toBeNull();
});

it('loads more only on demand and polls every loaded page using fresh cursors without duplicates', async () => {
  // Control interval ticks, while HTTP and Testing Library timeout timers stay real.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  try {
    let version = 0;
    const cursors: string[] = [];
    server.use(
      http.get('*/api/tickets', ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor') ?? 'first';
        cursors.push(`${version}:${cursor}`);
        if (cursor === 'first')
          return HttpResponse.json({
            items: [data.tickets[version ? 2 : 0]],
            next_cursor: version ? 'fresh' : 'next',
          });
        return HttpResponse.json({ items: [data.tickets[version ? 0 : 1]], next_cursor: null });
      }),
    );
    const { client, unmount } = mount('/tickets', 100);
    await screen.findByRole('link', { name: 'tk_sample' });
    expect(cursors.some((cursor) => cursor.endsWith(':next'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: '더 보기' }));
    await screen.findByRole('link', { name: 'tk_cloud' });
    version = 1;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    await waitFor(() =>
      expect(screen.queryByRole('link', { name: 'tk_cloud' })).not.toBeInTheDocument(),
    );
    expect(screen.getAllByRole('link', { name: /^tk_/ }).map((link) => link.textContent)).toEqual([
      'tk_custom',
      'tk_sample',
    ]);
    expect(cursors).toContain('1:fresh');
    expect(cursors).not.toContain('1:next');
    unmount();
    client.clear();
  } finally {
    vi.useRealTimers();
  }
});

it('distinguishes list loading, errors, retry and empty results', async () => {
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ error: { code: 'internal', message: '목록 실패' } }, { status: 500 }),
    ),
  );
  mount();
  expect(screen.getByText('티켓 불러오는 중…')).toBeInTheDocument();
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('목록 실패');
  server.use(http.get('*/api/tickets', () => HttpResponse.json({ items: [], next_cursor: null })));
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByText('티켓이 없습니다.')).toBeInTheDocument();
});

it('retries failed lookup without presenting it as a null asset', async () => {
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ items: [data.tickets[0]], next_cursor: null }),
    ),
    http.get('*/api/alerts/:id', () =>
      HttpResponse.json({ error: { code: 'internal', message: '알럿 실패' } }, { status: 500 }),
    ),
  );
  mount();
  const error = await screen.findByRole('alert');
  expect(error).toHaveTextContent('알럿 실패');
  expect(screen.queryByText('자산 정보 없음')).not.toBeInTheDocument();
  server.use(http.get('*/api/alerts/:id', () => HttpResponse.json(data.alerts[0])));
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByText('web-01')).toBeInTheDocument();
});

it('shows all statuses and nullable verdicts, multiple alerts, shared assets and privileged accounts', async () => {
  const user = userEvent.setup();
  mount();
  expect(await screen.findByRole('link', { name: 'tk_tie_a' })).toBeInTheDocument();
  // One alert card per ticket row, so the shared asset and privileged account of al_cloud
  // appear once for every ticket that lists it.
  const shared = data.tickets.filter((item) => item.alert_ids.includes('al_cloud')).length;
  expect(await screen.findAllByText('공용 자산')).toHaveLength(shared);
  expect(screen.getAllByText('관리자 계정')).toHaveLength(shared);
  expect(screen.getAllByText('신규')).toHaveLength(3);
  await user.click(screen.getByRole('button', { name: 'tk_tie_a 복사' }));
  expect(await navigator.clipboard.readText()).toBe('tk_tie_a');
  await user.click(screen.getByRole('button', { name: '다크 모드' }));
  expect(document.documentElement).toHaveClass('dark');
  await user.click(screen.getByRole('button', { name: '라이트 모드' }));
  expect(document.documentElement).not.toHaveClass('dark');
  await user.click(screen.getByRole('link', { name: 'tk_tie_a' }));
  expect(await screen.findByRole('heading', { name: '티켓 tk_tie_a' })).toBeInTheDocument();
});

it('keeps loaded rows when the next page fails and retries the same cursor', async () => {
  let failed = true;
  server.use(
    http.get('*/api/tickets', ({ request }) => {
      if (!new URL(request.url).searchParams.has('cursor'))
        return HttpResponse.json({ items: [data.tickets[0]], next_cursor: 'next' });
      if (failed)
        return HttpResponse.json(
          { error: { code: 'internal', message: '다음 페이지 실패' } },
          { status: 500 },
        );
      return HttpResponse.json({ items: [data.tickets[1]], next_cursor: null });
    }),
  );
  mount();
  await screen.findByRole('link', { name: 'tk_sample' });
  await userEvent.click(screen.getByRole('button', { name: '더 보기' }));
  const error = await screen.findByRole('alert');
  expect(screen.getByRole('link', { name: 'tk_sample' })).toBeInTheDocument();
  failed = false;
  await userEvent.click(within(error).getByRole('button', { name: '다시 시도' }));
  expect(await screen.findByRole('link', { name: 'tk_cloud' })).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /^tk_/ })).toHaveLength(2);
});

it('makes evidence IDs copyable while keeping untrusted references as text', async () => {
  const user = userEvent.setup();
  server.use(
    http.get('*/api/tickets', () =>
      HttpResponse.json({ items: [data.tickets[0]], next_cursor: null }),
    ),
  );
  mount();
  const reference = data.tickets[0].verdict!.evidence[0].ref_id;
  await user.click(await screen.findByRole('button', { name: `${reference} 복사` }));
  expect(await navigator.clipboard.readText()).toBe(reference);
});

it('refreshes three loaded pages atomically, retries failed polling, and removes obsolete pages when results shrink', async () => {
  // A real 100ms poll can disable '더 보기' between the enabled check and the click.
  // Control interval ticks, while HTTP and Testing Library timeout timers stay real.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  try {
    let version = 0;
    let fail = false;
    const requests: string[] = [];
    server.use(
      http.get('*/api/tickets', ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor') ?? 'first';
        requests.push(`${version}:${cursor}`);
        if (version === 2)
          return HttpResponse.json({ items: [data.tickets[3]], next_cursor: null });
        const page =
          cursor === 'first'
            ? 0
            : cursor === `${version}-second`
              ? 1
              : cursor === `${version}-third`
                ? 2
                : -1;
        if (page < 0)
          return HttpResponse.json(
            { error: { code: 'invalid_input', message: 'stale cursor' } },
            { status: 400 },
          );
        if (fail && page === 2)
          return HttpResponse.json(
            { error: { code: 'internal', message: '폴링 실패' } },
            { status: 500 },
          );
        const order = version === 0 ? [0, 1, 2] : [2, 0, 4];
        return HttpResponse.json({
          items: [data.tickets[order[page]]],
          next_cursor: page === 2 ? null : `${version}-${page === 0 ? 'second' : 'third'}`,
        });
      }),
    );
    const { client, unmount } = mount('/tickets', 100);
    const poll = () =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(100);
      });
    const ids = () => screen.getAllByRole('link', { name: /^tk_/ }).map((link) => link.textContent);
    await screen.findByRole('link', { name: 'tk_sample' });
    for (const id of ['tk_cloud', 'tk_custom']) {
      await waitFor(() => expect(screen.getByRole('button', { name: '더 보기' })).toBeEnabled());
      await userEvent.click(screen.getByRole('button', { name: '더 보기' }));
      await screen.findByRole('link', { name: id });
    }
    fail = true;
    version = 1;
    await poll();
    await screen.findByText('폴링 실패');
    expect(ids()).toEqual(['tk_sample', 'tk_cloud', 'tk_custom']);
    // A failed refresh must not combine the new first pages with stale trailing pages.
    fail = false;
    await poll();
    await waitFor(() => expect(ids()).toEqual(['tk_custom', 'tk_sample', 'tk_later']));
    expect(requests).toEqual(expect.arrayContaining(['1:first', '1:1-second', '1:1-third']));
    expect(requests).not.toContain('1:0-second');
    version = 2;
    await poll();
    await waitFor(() => expect(ids()).toEqual(['tk_tie_z']));
    expect(
      requests
        .filter((request) => request.startsWith('2:'))
        .every((request) => request === '2:first'),
    ).toBe(true);
    unmount();
    client.clear();
  } finally {
    vi.useRealTimers();
  }
});

it('uses only the approved GET APIs at /tickets', async () => {
  const path = '/tickets';
  const requests: string[] = [];
  const listener = ({ request }: { request: Request }) =>
    requests.push(`${request.method} ${new URL(request.url).pathname}`);
  server.events.on('request:start', listener);
  try {
    mount(path);
    await screen.findAllByText('web-01');
    expect(requests.length).toBeGreaterThan(0);
    expect(
      requests.every((request) => /^GET \/api\/(tickets|metrics|alerts\/[^/]+)$/.test(request)),
    ).toBe(true);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('renders null account and verdict, registered entity types and local timestamps without interpreting values', async () => {
  const ticket = structuredClone(data.tickets[0]);
  ticket.verdict = null;
  ticket.entities = [{ type: 'example.device', value: untrusted.input_excerpt }];
  const alert = structuredClone(data.alerts[0]);
  alert.src_asset = null;
  alert.dst_asset = null;
  alert.user_info = null;
  alert.rule_name = untrusted.output_excerpt;
  server.use(
    http.get('*/api/tickets', () => HttpResponse.json({ items: [ticket], next_cursor: null })),
    http.get('*/api/alerts/:id', () => HttpResponse.json(alert)),
  );
  const { container } = mount();
  await screen.findByText(untrusted.output_excerpt, { exact: false });
  expect(screen.getAllByText('자산 정보 없음')).toHaveLength(2);
  expect(screen.getAllByText('없음').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText(/example.device/)).toHaveTextContent(untrusted.input_excerpt);
  for (const time of container.querySelectorAll('time')) {
    const value = Number(time.getAttribute('title'));
    expect(time).toHaveTextContent(new Date(value).toLocaleString());
    expect(time).toHaveAttribute('datetime', new Date(value).toISOString());
  }
  expect(container.querySelector('a[href^="https://example.com"], b')).toBeNull();
});
