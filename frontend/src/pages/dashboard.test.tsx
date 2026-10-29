import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import { data, metrics } from '../mocks/data';
import untrusted from '../../../tests/fixtures/frontend/untrusted-text.json';

const regions = [
  'Ticket 현황',
  'Incident 현황',
  'Case 현황',
  '헌팅 현황',
  '룰 제안 현황',
  '검토 지표',
];

function mount(path = '/') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return Object.assign(
    render(
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <RouterProvider router={router} />
        </ThemeProvider>
      </QueryClientProvider>,
    ),
    { client },
  );
}

const region = (name: string) => within(screen.getByRole('region', { name }));
const page = (items: unknown[], next_cursor: string | null = null) =>
  HttpResponse.json({ items, next_cursor });

function recordRequests() {
  const paths: string[] = [];
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    paths.push(url.pathname + url.search);
  });
  return paths;
}

// The mock derives the current waiting count from its ticket state.
const waiting = data.tickets.filter((ticket) => ticket.status === 'awaiting_human').length;

async function ready(skip: string[] = []) {
  if (!skip.includes('검토 지표')) await screen.findByText(`검토 대기 ${waiting}건`);
  for (const name of regions.slice(1, 5).filter((item) => !skip.includes(item)))
    await waitFor(() => expect(region(name).getByText(/^불러온 \d+건 기준/)).toBeInTheDocument());
}

// The dashboard is read-only: every request in every test here must be a GET.
const methods: string[] = [];
beforeEach(() => {
  methods.length = 0;
  server.events.on('request:start', ({ request }) => methods.push(request.method));
});
afterEach(() => {
  server.events.removeAllListeners();
  expect(methods.length).toBeGreaterThan(0);
  expect(new Set(methods)).toEqual(new Set(['GET']));
});

it('shows one h1, an h2 per region and every work entry link', async () => {
  const { container } = mount();
  await ready();
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  expect(screen.getByRole('heading', { level: 1, name: '운영 대시보드' })).toBeInTheDocument();
  expect(screen.getAllByRole('heading', { level: 2 }).map((item) => item.textContent)).toEqual(
    regions,
  );
  expect(container.querySelectorAll('h3, h4, h5, h6')).toHaveLength(0);
  const entries: [string, string, string][] = [
    ['Ticket 현황', '검토 대기함으로 이동', '/review'],
    ['Ticket 현황', '전체 티켓으로 이동', '/tickets'],
    ['Incident 현황', 'Incident 목록으로 이동', '/incidents'],
    ['Case 현황', 'Case 목록으로 이동', '/cases'],
    ['헌팅 현황', '헌팅 결과로 이동', '/hunts'],
    ['룰 제안 현황', '룰 제안으로 이동', '/rules'],
  ];
  for (const [name, label, href] of entries)
    expect(region(name).getByRole('link', { name: label })).toHaveAttribute('href', href);
});

it('uses tickets_awaiting_human from metrics, not the loaded ticket list length', async () => {
  server.use(
    http.get('*/api/metrics', ({ request }) => {
      const query = new URL(request.url).searchParams;
      return HttpResponse.json({
        ...metrics,
        from: Number(query.get('from')),
        to: Number(query.get('to')),
        tickets_awaiting_human: 42,
      });
    }),
    http.get('*/api/tickets', () => page([data.tickets[0]], '1')),
  );
  mount();
  expect(await region('Ticket 현황').findByText('검토 대기 42건')).toBeInTheDocument();
  expect(await region('Ticket 현황').findByText('불러온 1건 기준 · 더 있음')).toBeInTheDocument();
});

it('shows the raw metric values and the period without computing any ratio', async () => {
  const from = new Date();
  from.setHours(0, 0, 0, 0);
  server.use(
    http.get('*/api/metrics', ({ request }) => {
      const query = new URL(request.url).searchParams;
      return HttpResponse.json({
        from: Number(query.get('from')),
        to: Number(query.get('to')),
        available: true,
        tickets_total: 30,
        tickets_awaiting_human: 4,
        l1_reviews_total: 12,
        l1_overturned: 3,
        l2_reviews_total: 7,
        l2_rejects_by_type: { missing_step: 2, 'example.plugin_reject': 1 },
        incident_members_by_source: { l1: 5, human_l1: 2, l3: 1 },
        normalize_failures_by_reason: { bad_value: 6, 'example.new_reason': 0 },
      });
    }),
  );
  const { container } = mount();
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByText('L1 검토 12건 / 뒤집음 3건')).toBeInTheDocument();
  expect(metricsRegion.getByText('L2 검토 7건')).toBeInTheDocument();
  expect(metricsRegion.getByText('기간 안 티켓 30건')).toBeInTheDocument();
  const rejects = within(metricsRegion.getByRole('table', { name: 'L2 반려 유형별 수' }));
  expect(rejects.getAllByRole('row').map((row) => row.textContent)).toEqual([
    '누락된 단계2건',
    'example.plugin_reject1건',
  ]);
  const sources = within(
    metricsRegion.getByRole('table', { name: 'Incident 묶음 항목 출처별 수' }),
  );
  expect(sources.getAllByRole('row').map((row) => row.textContent)).toEqual([
    'L1 판정5건',
    '사람 확정2건',
    'L31건',
  ]);
  const failures = within(metricsRegion.getByRole('table', { name: '정규화 실패 사유별 수' }));
  expect(failures.getAllByRole('row').map((row) => row.textContent)).toEqual([
    'bad_value6건',
    'example.new_reason0건',
  ]);
  // The period sent to the API is shown as received, with epoch ms in the tooltip.
  const times = metricsRegion.getAllByRole('time');
  expect(times[0]).toHaveAttribute('title', String(from.getTime()));
  expect(times[0]).toHaveTextContent(from.toLocaleString());
  expect(metricsRegion.getByText(/현재 검토 대기 건수는 기간과 관계없이/)).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/%/);
});

it('shows "없음" for an empty metric breakdown', async () => {
  server.use(
    http.get('*/api/metrics', ({ request }) => {
      const query = new URL(request.url).searchParams;
      return HttpResponse.json({
        ...metrics,
        from: Number(query.get('from')),
        to: Number(query.get('to')),
        l2_rejects_by_type: {},
      });
    }),
  );
  mount();
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByText('L2 반려 유형별 수: 없음')).toBeInTheDocument();
  expect(metricsRegion.queryByRole('table', { name: 'L2 반려 유형별 수' })).toBeNull();
});

it('counts only the loaded first page per status, keeps raw unknown values and API order', async () => {
  const base = data.incidents[0];
  const incidents = [
    {
      ...base,
      incident_id: 'in_z',
      title: 'Z',
      status: 'open',
      review_state: 'analyzing',
      first_seen: 3,
    },
    {
      ...base,
      incident_id: 'in_a',
      title: 'A',
      status: 'example.paused',
      review_state: 'awaiting_review',
      first_seen: 1,
    },
    {
      ...base,
      incident_id: 'in_m',
      title: 'M',
      status: 'open',
      review_state: 'example.queued',
      first_seen: 2,
    },
  ];
  server.use(http.get('*/api/incidents', () => page(incidents, '3')));
  mount();
  const incident = region('Incident 현황');
  expect(await incident.findByText('불러온 3건 기준 · 더 있음')).toBeInTheDocument();
  const status = within(incident.getByRole('table', { name: 'Incident 상태별 수' }));
  expect(status.getAllByRole('row').map((row) => row.textContent)).toEqual([
    '열림2건',
    'example.paused1건',
  ]);
  const review = within(incident.getByRole('table', { name: 'Incident L2 검토 상태별 수' }));
  expect(review.getAllByRole('row').map((row) => row.textContent)).toEqual([
    'L2 분석 중1건',
    'L2 검토 대기1건',
    'example.queued1건',
  ]);
  const top = within(incident.getByRole('list', { name: 'Incident 상단 항목' }));
  expect(top.getAllByRole('link').map((link) => link.textContent)).toEqual([
    'in_z',
    'in_a',
    'in_m',
  ]);
  expect(top.getByRole('link', { name: 'in_a' })).toHaveAttribute('href', '/incidents/in_a');
});

it('shows at most five top items from the first page, in order, for every list', async () => {
  const many = <T extends object>(item: T, key: keyof T, prefix: string) =>
    Array.from({ length: 7 }, (_, index) => ({ ...item, [key]: `${prefix}_${6 - index}` }));
  server.use(
    http.get('*/api/tickets', () => page(many(data.tickets[0], 'ticket_id', 'tk'))),
    http.get('*/api/incidents', () => page(many(data.incidents[0], 'incident_id', 'in'))),
    http.get('*/api/cases', () => page(many(data.cases[0], 'case_id', 'cs'))),
    http.get('*/api/hunts', () => page(many(data.hunts[0], 'hunt_id', 'hn'))),
    http.get('*/api/rules', () => page(many(data.rules[0], 'proposal_id', 'rp'))),
  );
  mount();
  const lists: [string, string, string][] = [
    ['Ticket 현황', 'Ticket 상단 항목', 'tk'],
    ['Incident 현황', 'Incident 상단 항목', 'in'],
    ['Case 현황', 'Case 상단 항목', 'cs'],
    ['헌팅 현황', '헌팅 결과 상단 항목', 'hn'],
    ['룰 제안 현황', '룰 제안 상단 항목', 'rp'],
  ];
  for (const [name, list, prefix] of lists) {
    const top = within(await region(name).findByRole('list', { name: list }));
    expect(top.getAllByRole('link').map((link) => link.textContent)).toEqual(
      [6, 5, 4, 3, 2].map((index) => `${prefix}_${index}`),
    );
    expect(region(name).getByText('불러온 7건 기준')).toBeInTheDocument();
  }
  expect(screen.queryByText(/최근/)).toBeNull();
});

it('counts Case, Hunt and Rule statuses from the loaded page only', async () => {
  server.use(
    http.get('*/api/cases', () =>
      page([
        { ...data.cases[0], case_id: 'cs_1', status: 'responding' },
        { ...data.cases[0], case_id: 'cs_2', status: 'example.hold' },
        { ...data.cases[0], case_id: 'cs_3', status: 'responding' },
      ]),
    ),
    http.get('*/api/hunts', () =>
      page([
        { ...data.hunts[0], hunt_id: 'hn_1', is_anomaly: false },
        { ...data.hunts[0], hunt_id: 'hn_2', is_anomaly: true },
        { ...data.hunts[0], hunt_id: 'hn_3', is_anomaly: true },
      ]),
    ),
    http.get('*/api/rules', () =>
      page([
        { ...data.rules[0], proposal_id: 'rp_1', status: 'draft' },
        { ...data.rules[0], proposal_id: 'rp_2', status: 'example.staged' },
      ]),
    ),
  );
  mount();
  const cases = within(await region('Case 현황').findByRole('table', { name: 'Case 상태별 수' }));
  expect(cases.getAllByRole('row').map((row) => row.textContent)).toEqual([
    '대응 중2건',
    'example.hold1건',
  ]);
  const hunts = within(
    await region('헌팅 현황').findByRole('table', { name: '헌팅 결과 이상 징후별 수' }),
  );
  expect(hunts.getAllByRole('row').map((row) => row.textContent)).toEqual([
    '이상 없음1건',
    '이상 징후2건',
  ]);
  const rules = within(
    await region('룰 제안 현황').findByRole('table', { name: '룰 제안 상태별 수' }),
  );
  expect(rules.getAllByRole('row').map((row) => row.textContent)).toEqual([
    '초안1건',
    'example.staged1건',
  ]);
  expect(region('Case 현황').getByText('불러온 3건 기준')).toBeInTheDocument();
});

it('calls only the documented list and metrics APIs, once each, with no per-row detail', async () => {
  const paths = recordRequests();
  mount();
  await ready();
  const names = paths.map((path) => path.replace(/\?.*$/, ''));
  expect([...names].sort()).toEqual(
    [
      '/api/cases',
      '/api/hunts',
      '/api/incidents',
      '/api/metrics',
      '/api/rules',
      '/api/tickets',
    ].sort(),
  );
  expect(paths).toContain('/api/tickets?status=awaiting_human');
  expect(paths.some((path) => path.startsWith('/api/normalize-failures'))).toBe(false);
  expect(paths.some((path) => /^\/api\/[a-z-]+\/[^/?]+/.test(path))).toBe(false);
});

it.each([
  ['cases', 'Case 현황', 'cs_back', () => page([{ ...data.cases[0], case_id: 'cs_back' }])],
  ['rules', '룰 제안 현황', 'rp_back', () => page([{ ...data.rules[0], proposal_id: 'rp_back' }])],
] as const)(
  'keeps a %s failure inside its region and retries only that query',
  async (path, name, back, recovered) => {
    let fail = true;
    server.use(
      http.get(`*/api/${path}`, () =>
        fail
          ? HttpResponse.json(
              { error: { code: 'internal', message: `${path} down` } },
              { status: 500 },
            )
          : recovered(),
      ),
    );
    mount();
    await ready([name]);
    const failed = region(name);
    expect(await failed.findByRole('alert')).toHaveTextContent(`${path} down`);
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    for (const other of regions.slice(0, 5).filter((item) => item !== name))
      expect(region(other).getByRole('list', { name: /상단 항목$/ })).toBeInTheDocument();
    expect(region('검토 지표').getByText(/^L1 검토/)).toBeInTheDocument();
    const paths = recordRequests();
    fail = false;
    await userEvent.click(failed.getByRole('button', { name: '다시 시도' }));
    expect(await failed.findByRole('link', { name: back })).toBeInTheDocument();
    expect(paths.map((item) => item.replace(/\?.*$/, ''))).toEqual([`/api/${path}`]);
    expect(screen.queryByRole('alert')).toBeNull();
  },
);

// A route the running API does not have answers with FastAPI's default 404 body.
const missingRoute = () => HttpResponse.json({ detail: 'Not Found' }, { status: 404 });

it.each([
  ['tickets', 'Ticket 현황'],
  ['incidents', 'Incident 현황'],
  ['cases', 'Case 현황'],
  ['hunts', '헌팅 현황'],
  ['rules', '룰 제안 현황'],
] as const)('shows a neutral "아직 없음" when /api/%s is not there (404)', async (path, name) => {
  server.use(http.get(`*/api/${path}`, missingRoute));
  mount();
  await ready([name]);
  const missing = region(name);
  expect(await missing.findByText('아직 없음')).toBeInTheDocument();
  expect(missing.queryByRole('alert')).toBeNull();
  expect(missing.queryByRole('button', { name: '다시 시도' })).toBeNull();
  expect(missing.queryByRole('list', { name: /상단 항목$/ })).toBeNull();
  expect(screen.queryByRole('alert')).toBeNull();
  for (const other of regions.slice(0, 5).filter((item) => item !== name))
    expect(region(other).getByRole('list', { name: /상단 항목$/ })).toBeInTheDocument();
  expect(region('검토 지표').getByText(/^L1 검토/)).toBeInTheDocument();
});

it('shows "지표 없음" without an error when /api/metrics is not there (404)', async () => {
  server.use(http.get('*/api/metrics', missingRoute));
  mount();
  await ready(['검토 지표']);
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByText('지표 없음')).toBeInTheDocument();
  expect(metricsRegion.queryByRole('button', { name: '다시 시도' })).toBeNull();
  expect(screen.queryByRole('alert')).toBeNull();
  const tickets = region('Ticket 현황');
  expect(tickets.getByText('검토 대기 건수: 지표 없음')).toBeInTheDocument();
  expect(tickets.queryByText(/^검토 대기 \d+건$/)).toBeNull();
  expect(tickets.getByRole('list', { name: 'Ticket 상단 항목' })).toBeInTheDocument();
});

// The implemented route says "nothing to count" with available=false (#103). Unlike the
// 404 above it is a normal answer, so neither region may show an error or a zero.
const emptyMetrics = ({ request }: { request: Request }) => {
  const query = new URL(request.url).searchParams;
  return HttpResponse.json({
    from: Number(query.get('from')),
    to: Number(query.get('to')),
    available: false,
  });
};

it('shows "지표 없음" without an error or a zero when metrics are not available', async () => {
  server.use(http.get('*/api/metrics', emptyMetrics));
  mount();
  await ready(['검토 지표']);
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByText('지표 없음')).toBeInTheDocument();
  expect(metricsRegion.queryByRole('button', { name: '다시 시도' })).toBeNull();
  expect(metricsRegion.queryByText(/0건/)).toBeNull();
  expect(metricsRegion.queryByText(/^L1 검토/)).toBeNull();
  expect(metricsRegion.queryByText(/집계 기간/)).toBeNull();
  expect(screen.queryByRole('alert')).toBeNull();
  const tickets = region('Ticket 현황');
  expect(tickets.getByText('검토 대기 건수: 지표 없음')).toBeInTheDocument();
  expect(tickets.queryByText(/^검토 대기 \d+건$/)).toBeNull();
});

it('keeps a real failure visible when the last answer was available=false', async () => {
  let fail = false;
  server.use(
    http.get('*/api/metrics', (info) => {
      if (!fail) return emptyMetrics(info);
      return HttpResponse.json(
        { error: { code: 'internal', message: 'metrics down' } },
        { status: 500 },
      );
    }),
  );
  const view = mount();
  await ready(['검토 지표']);
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByText('지표 없음')).toBeInTheDocument();
  fail = true;
  await view.client.refetchQueries({ queryKey: ['metrics', 'current-waiting'] });
  // An older available=false must not hide the failed refresh (docs/frontend.md F6).
  expect(await metricsRegion.findByRole('alert')).toHaveTextContent('metrics down');
  expect(
    region('Ticket 현황').getByText(
      '검토 대기 건수를 확인할 수 없습니다. 검토 지표 영역에서 다시 시도하세요.',
    ),
  ).toBeInTheDocument();
});

it('keeps a metrics failure inside the metrics region and never falls back to the list length', async () => {
  let fail = true;
  server.use(
    http.get('*/api/metrics', ({ request }) => {
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: 'metrics down' } },
          { status: 500 },
        );
      const query = new URL(request.url).searchParams;
      return HttpResponse.json({
        ...metrics,
        from: Number(query.get('from')),
        to: Number(query.get('to')),
      });
    }),
  );
  mount();
  const metricsRegion = region('검토 지표');
  expect(await metricsRegion.findByRole('alert')).toHaveTextContent('metrics down');
  // A real failure says "지표 없음" and keeps the reason and the retry below it.
  expect(metricsRegion.getByText('지표 없음')).toBeInTheDocument();
  const tickets = region('Ticket 현황');
  expect(await tickets.findByRole('list', { name: 'Ticket 상단 항목' })).toBeInTheDocument();
  expect(
    tickets.getByText('검토 대기 건수를 확인할 수 없습니다. 검토 지표 영역에서 다시 시도하세요.'),
  ).toBeInTheDocument();
  expect(tickets.queryByText(/^검토 대기 \d+건$/)).toBeNull();
  expect(screen.getAllByRole('alert')).toHaveLength(1);
  const paths = recordRequests();
  fail = false;
  await userEvent.click(metricsRegion.getByRole('button', { name: '다시 시도' }));
  expect(await tickets.findByText(`검토 대기 ${waiting}건`)).toBeInTheDocument();
  expect(paths.map((path) => path.replace(/\?.*$/, ''))).toEqual(['/api/metrics']);
});

it('does not keep showing an older waiting count after a metrics refresh fails', async () => {
  let fail = false;
  server.use(
    http.get('*/api/metrics', ({ request }) => {
      if (fail)
        return HttpResponse.json(
          { error: { code: 'internal', message: 'metrics down' } },
          { status: 500 },
        );
      const query = new URL(request.url).searchParams;
      return HttpResponse.json({
        ...metrics,
        from: Number(query.get('from')),
        to: Number(query.get('to')),
        tickets_awaiting_human: 7,
      });
    }),
  );
  const { client } = mount();
  const tickets = region('Ticket 현황');
  expect(await tickets.findByText('검토 대기 7건')).toBeInTheDocument();
  fail = true;
  await client.refetchQueries({ queryKey: ['metrics'] });
  expect(await region('검토 지표').findByRole('alert')).toHaveTextContent('metrics down');
  expect(
    tickets.getByText('검토 대기 건수를 확인할 수 없습니다. 검토 지표 영역에서 다시 시도하세요.'),
  ).toBeInTheDocument();
  expect(tickets.queryByText('검토 대기 7건')).toBeNull();
  // Older metrics stay visible only with an explicit note.
  expect(
    region('검토 지표').getByText('아래는 마지막으로 받은 값입니다. 갱신에 실패했습니다.'),
  ).toBeInTheDocument();
});

it('marks an older list as last received when its refresh fails', async () => {
  let fail = false;
  server.use(
    http.get('*/api/rules', () =>
      fail
        ? HttpResponse.json({ error: { code: 'internal', message: 'rules down' } }, { status: 500 })
        : page([data.rules[0]]),
    ),
  );
  const { client } = mount();
  const rules = region('룰 제안 현황');
  expect(await rules.findByText('불러온 1건 기준')).toBeInTheDocument();
  expect(rules.queryByText(/마지막으로 받은 값/)).toBeNull();
  fail = true;
  await client.refetchQueries({ queryKey: ['rules'] });
  expect(await rules.findByRole('alert')).toHaveTextContent('rules down');
  expect(
    rules.getByText('아래는 마지막으로 받은 값입니다. 갱신에 실패했습니다.'),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/마지막으로 받은 값/)).toHaveLength(1);
});

it('shows loading and empty states per region independently', async () => {
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  server.use(
    http.get('*/api/rules', async () => {
      await held;
      return page([]);
    }),
    http.get('*/api/hunts', () => page([])),
  );
  mount();
  expect(await region('헌팅 현황').findByText('헌팅 결과가 없습니다.')).toBeInTheDocument();
  expect(region('룰 제안 현황').getByRole('status')).toHaveTextContent('룰 제안 불러오는 중…');
  expect(
    await region('Case 현황').findByRole('list', { name: 'Case 상단 항목' }),
  ).toBeInTheDocument();
  release();
  expect(await region('룰 제안 현황').findByText('룰 제안이 없습니다.')).toBeInTheDocument();
  expect(region('헌팅 현황').queryByRole('table')).toBeNull();
});

it('shows untrusted titles and hypotheses as plain text without auto links', async () => {
  const text = `${untrusted.payload} ${untrusted.summary}`;
  server.use(
    http.get('*/api/incidents', () => page([{ ...data.incidents[0], title: text }])),
    http.get('*/api/cases', () => page([{ ...data.cases[0], title: untrusted.input_excerpt }])),
    http.get('*/api/hunts', () =>
      page([{ ...data.hunts[0], hypothesis: untrusted.output_excerpt }]),
    ),
    http.get('*/api/rules', () => page([{ ...data.rules[0], title: untrusted.summary }])),
    http.get('*/api/tickets', () =>
      page([
        { ...data.tickets[0], handling_type: '<b>example.plugin</b>', status: 'example.<i>x</i>' },
      ]),
    ),
  );
  const { container } = mount();
  expect(await region('Incident 현황').findByText(text)).toBeInTheDocument();
  expect(await region('Case 현황').findByText(untrusted.input_excerpt)).toBeInTheDocument();
  expect(await region('헌팅 현황').findByText(untrusted.output_excerpt)).toBeInTheDocument();
  expect(await region('룰 제안 현황').findByText(untrusted.summary)).toBeInTheDocument();
  expect(
    await region('Ticket 현황').findByText(/^<b>example\.plugin<\/b> · 우선순위/),
  ).toBeInTheDocument();
  expect(region('Ticket 현황').getAllByText('example.<i>x</i>').length).toBeGreaterThan(0);
  expect(container.querySelector('script, img, iframe, b, i')).toBeNull();
  expect((window as { compromised?: boolean }).compromised).toBeUndefined();
  for (const link of container.querySelectorAll('a'))
    expect(link.getAttribute('href')).toMatch(/^\/(?!\/)/);
});

it('activates the dashboard menu item only at / and reaches every link by keyboard', async () => {
  const { unmount } = mount('/');
  const nav = within(screen.getByRole('navigation', { name: '주 메뉴' }));
  const home = nav.getByRole('link', { name: '대시보드' });
  expect(home).toHaveAttribute('href', '/');
  expect(home).toHaveAttribute('aria-current', 'page');
  await ready();
  const main = screen.getByRole('main');
  const targets = within(main).getAllByRole('link');
  const reached = new Set<Element>();
  for (let step = 0; step < 200 && reached.size < targets.length; step++) {
    await userEvent.tab();
    if (document.activeElement && main.contains(document.activeElement))
      reached.add(document.activeElement);
  }
  for (const target of targets) expect(reached).toContain(target);
  unmount();
  for (const path of ['/cases', '/rules', '/hunts/ht_web', '/tickets/tk_sample']) {
    const view = mount(path);
    const menu = within(screen.getByRole('navigation', { name: '주 메뉴' }));
    expect(menu.getByRole('link', { name: '대시보드' })).not.toHaveAttribute('aria-current');
    view.unmount();
  }
});
