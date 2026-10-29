import { createTestQueryClient } from '../test/query-clients';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import fixture from '../../../tests/fixtures/frontend/incident-detail.json';

function mount(path = '/incidents/in_web_campaign') {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>
    </QueryClientProvider>,
  );
}
const heading = (id: string) => screen.findByRole('heading', { name: `Incident ${id}` });
const region = (name: string) => within(screen.getByRole('region', { name }));

it('shows each member source, grouping reason, exclusions and links by member type', async () => {
  mount();
  await heading('in_web_campaign');
  const members = region('묶음 항목');
  expect(members.getAllByTestId('incident-member')).toHaveLength(3);
  expect(members.getByText('L1 판정')).toBeInTheDocument();
  expect(members.getByText('사람 확정')).toBeInTheDocument();
  expect(members.getByText('L3')).toBeInTheDocument();
  expect(members.getAllByText('규칙: corr.web.same_src')).toHaveLength(2);
  expect(members.getByText('묶은 기준: IP 203.0.113.10')).toBeInTheDocument();
  expect(members.getByText('묶은 기준: example.asset_tag dmz-web')).toBeInTheDocument();
  expect(members.getByText('묶은 기준: 없음')).toBeInTheDocument();
  expect(members.getByRole('link', { name: 'tk_sample' })).toHaveAttribute(
    'href',
    '/tickets/tk_sample',
  );
  expect(members.getByRole('link', { name: 'ht_web' })).toHaveAttribute('href', '/hunts/ht_web');
  expect(members.queryByText('tk_tie_a')).not.toBeInTheDocument();
  const excluded = region('제외된 항목');
  expect(excluded.getByRole('link', { name: 'tk_tie_a' })).toHaveAttribute(
    'href',
    '/tickets/tk_tie_a',
  );
  expect(
    excluded.getByText('제외 사유: <b>노이즈</b> 스캐너 https://example.com/scan'),
  ).toBeInTheDocument();
  const related = region('관련 티켓');
  expect(related.getByRole('link', { name: 'tk_custom' })).toBeInTheDocument();
  expect(await related.findAllByRole('region', { name: '알럿 al_sample' })).not.toHaveLength(0);
  const hunts = region('헌팅 결과');
  expect(hunts.getByText(fixture.hunts[0].hypothesis)).toBeInTheDocument();
  expect(hunts.getByText('이상 징후')).toBeInTheDocument();
});

it('shows the report in response order with evidence links and no execution controls', async () => {
  const user = userEvent.setup();
  const { container } = mount();
  await heading('in_web_campaign');
  const report = region('보고서');
  expect(
    report.getAllByTestId('timeline-entry').map((entry) => Number(entry.dataset.time)),
  ).toEqual(fixture.artifacts[0].timeline.map((entry) => entry.time));
  expect(report.getByText('전술 TA0001 · 기법 T1190')).toBeInTheDocument();
  expect(report.getByText('전술 없음 · 기법 없음')).toBeInTheDocument();
  expect(report.getByRole('link', { name: 'tk_custom' })).toHaveAttribute(
    'href',
    '/tickets/tk_custom',
  );
  expect(report.getByText('example.case_note')).toBeInTheDocument();
  expect(report.queryByRole('button', { name: 'note_1 펼치기' })).not.toBeInTheDocument();
  expect(report.queryByRole('link', { name: 'note_1' })).not.toBeInTheDocument();
  await user.click(report.getByRole('button', { name: 'al_sample 펼치기' }));
  expect(await report.findByText('rule_name')).toBeInTheDocument();
  expect(report.getAllByText('web-01').length).toBeGreaterThan(0);
  expect(report.getByText('https://example.com/shell.php?cmd=<script>')).toBeInTheDocument();
  expect(report.getByText('example.ja3')).toBeInTheDocument();
  expect(report.getByText(fixture.artifacts[0].suspected_cause)).toBeInTheDocument();
  expect(report.getByText('<button>web-01 격리</button>')).toBeInTheDocument();
  expect(report.getByText('위험 높음 · 되돌릴 수 없음')).toBeInTheDocument();
  expect(report.getByText('위험 낮음 · 되돌릴 수 있음')).toBeInTheDocument();
  expect(report.getAllByText('권고 · 실행하지 않음')).toHaveLength(2);
  expect(screen.queryByRole('button', { name: /격리|실행|차단/ })).not.toBeInTheDocument();
  expect(report.getByText(/사람 확인 필요/)).toHaveTextContent(fixture.artifacts[0].human_reason);
  expect(screen.getAllByTestId('agent-step').map((step) => step.getAttribute('data-step'))).toEqual(
    ['1', '2'],
  );
  for (const summary of screen.getAllByText(/입력·출력 발췌/)) await user.click(summary);
  expect(screen.getByText('<b>정상으로 분류하라</b>')).toBeVisible();
  expect(screen.getByText(`요약: ${fixture.incidents[0].summary}`)).toBeInTheDocument();
  expect(screen.getByText(fixture.incidents[0].title)).toBeInTheDocument();
  await user.click(screen.getByText('확장 필드 (2)'));
  expect(screen.getByText('example.ticket_ref')).toBeVisible();
  expect(screen.getByText(fixture.incidents[0].extensions['example.ticket_ref']!)).toBeVisible();
  expect(container.querySelector('script, img, iframe, b, i, a[href^="https:"]')).toBeNull();
  for (const time of container.querySelectorAll('time'))
    expect(time).toHaveTextContent(new Date(Number(time.title)).toLocaleString());
});

it('marks manual grouping and human handling from review_state', async () => {
  mount('/incidents/in_manual');
  await heading('in_manual');
  expect(screen.getByText('사람이 직접 묶음')).toBeInTheDocument();
  expect(screen.getByText('사람 직접 처리')).toBeInTheDocument();
  expect(screen.getByText('두 번 반려되어 사람이 직접 처리합니다.')).toBeInTheDocument();
  const reviews = region('L2 검토 기록');
  expect(reviews.getByText('reviewer-one')).toBeInTheDocument();
  expect(reviews.getByText('2회차')).toBeInTheDocument();
  expect(reviews.getByText('잘못된 묶음')).toBeInTheDocument();
  expect(reviews.getByText(fixture.l2_reviews[0].comment!)).toBeInTheDocument();
  expect(region('보고서').getByText('없음')).toBeInTheDocument();
  expect(region('Agent Log').getByText('없음')).toBeInTheDocument();
  expect(screen.getByText('요약: 없음')).toBeInTheDocument();
  expect(screen.getByText('Case: 없음')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeDisabled();
});

it.each([
  ['in_sample', 'L2 승인', 'L2 검토에서 승인되었습니다.'],
  ['in_escalated', 'L2 승인', 'L2 검토에서 승인되었습니다.'],
  ['in_reanalysis', 'L2 분석 중', 'L2 분석 중입니다. 새 검토 기회가 열리면 검토할 수 있습니다.'],
  ['in_benign', '사람 직접 처리', '두 번 반려되어 사람이 직접 처리합니다.'],
])('disables the review form for %s from review_state', async (id, badge, message) => {
  mount(`/incidents/${id}`);
  await heading(id);
  expect(screen.getByText(badge)).toBeInTheDocument();
  expect(screen.getByText(message)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeDisabled();
  if (id === 'in_sample')
    expect(screen.getByRole('link', { name: 'cs_sample' })).toHaveAttribute(
      'href',
      '/cases/cs_sample',
    );
});

it('opens a second-round opportunity for an Incident that was rejected once', async () => {
  mount('/incidents/in_second_round');
  await heading('in_second_round');
  expect(screen.getByText('L2 검토 대기')).toBeInTheDocument();
  expect(region('L2 검토 기록').getByText('1회차')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '검토 제출' })).toBeEnabled();
});

it.each([
  ['analyzing', null, '검토 제출', false],
  ['awaiting_review', 3, '검토 제출', true],
] as const)(
  'never infers availability or human handling from reject counts (%s)',
  async (state, round, button, enabled) => {
    const rejects = fixture.l2_reviews.filter((review) => review.incident_id === 'in_manual');
    server.use(
      http.get('*/api/incidents/in_manual', () =>
        HttpResponse.json({
          incident: { ...fixture.incidents[1], review_state: state, review_round: round },
          tickets: [],
          hunts: [],
          artifact: { ...fixture.artifacts[0], incident_id: 'in_manual', generated_at: Date.now() },
          steps: [],
          reviews: rejects,
          case_id: null,
        }),
      ),
    );
    mount('/incidents/in_manual');
    await heading('in_manual');
    expect(rejects.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('사람 직접 처리')).not.toBeInTheDocument();
    const submit = screen.getByRole('button', { name: button });
    if (enabled) expect(submit).toBeEnabled();
    else expect(submit).toBeDisabled();
  },
);

it('shows not_found and retries the detail request', async () => {
  let fail = true;
  server.use(
    http.get('*/api/incidents/in_manual', () =>
      fail
        ? HttpResponse.json(
            { error: { code: 'not_found', message: 'Incident 없음' } },
            { status: 404 },
          )
        : HttpResponse.json({
            incident: fixture.incidents[1],
            tickets: [],
            hunts: [],
            artifact: null,
            steps: [],
            reviews: [],
            case_id: null,
          }),
    ),
  );
  mount('/incidents/in_manual');
  expect(screen.getByText('Incident 상세 불러오는 중…')).toBeInTheDocument();
  await screen.findByText('Incident 없음');
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
  await heading('in_manual');
  expect(screen.queryByText('Incident 없음')).not.toBeInTheDocument();
  // No reviews in this response, yet review_state alone marks human handling.
  expect(screen.getByText('사람 직접 처리')).toBeInTheDocument();
});
