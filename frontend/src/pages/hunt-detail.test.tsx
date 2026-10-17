import { createTestQueryClient } from '../test/query-clients';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import fixture from '../../../tests/fixtures/frontend/hunt-rule-detail.json';

const CLOUD = fixture.hunts[0];

function mount(path: string) {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return {
    ...render(
      <QueryClientProvider client={client}>
        <ThemeProvider>
          <RouterProvider router={router} />
        </ThemeProvider>
      </QueryClientProvider>,
    ),
    router,
  };
}
const heading = (id: string) => screen.findByRole('heading', { name: `헌팅 ${id}` });
const region = (name: string) => within(screen.getByRole('region', { name }));

it('shows C17 values, evidence, human reason and rule proposals as plain text', async () => {
  const { container } = mount('/hunts/ht_cloud_login');
  await heading('ht_cloud_login');
  expect(screen.getByRole('navigation', { name: '위치' })).toHaveTextContent('헌팅 결과');
  expect(screen.getByText(CLOUD.hypothesis)).toBeInTheDocument();
  expect(screen.getByText('이상 징후')).toBeInTheDocument();
  expect(screen.getByText('가설 기반')).toBeInTheDocument();
  expect(screen.getByText('Medium')).toBeInTheDocument();
  expect(screen.getByText('Incident: 없음')).toBeInTheDocument();
  expect(screen.getByText('룰 후보: 예')).toBeInTheDocument();
  expect(screen.getByText(CLOUD.human_reason!)).toBeInTheDocument();
  const content = region('헌팅 내용');
  expect(content.getByText('T1078.004')).toBeInTheDocument();
  expect(content.getByText(CLOUD.query_summary)).toBeInTheDocument();
  const evidence = region('근거');
  expect(evidence.getByText(CLOUD.evidence[0].note)).toBeInTheDocument();
  // Unknown registered ref_type: original string, copyable ID, no guessed lookup route.
  expect(evidence.getByText('example.flow')).toBeInTheDocument();
  expect(evidence.getByText('flow_cloud_77')).toBeInTheDocument();
  expect(evidence.queryByRole('button', { name: 'flow_cloud_77 펼치기' })).toBeNull();
  const created = screen.getByText(new Date(CLOUD.created_at).toLocaleString());
  expect(created).toHaveAttribute('title', String(CLOUD.created_at));
  const proposals = region('룰 제안');
  expect(proposals.getByRole('link', { name: 'rp_cloud_login' })).toHaveAttribute(
    'href',
    '/rules/rp_cloud_login',
  );
  expect(proposals.getByRole('link', { name: 'rp_cloud_rejected' })).toBeInTheDocument();
  expect(container.querySelector('script, img, b, i, a[href^="https:"]')).toBeNull();
});

it('expands event evidence through the documented event lookup', async () => {
  const user = userEvent.setup();
  mount('/hunts/ht_cloud_login');
  await heading('ht_cloud_login');
  await user.click(screen.getByRole('button', { name: 'ev_sample 펼치기' }));
  expect(await region('근거').findByText('event_id')).toBeInTheDocument();
});

it('links an anomaly grouped by Correlation to its Incident and orders the Agent Log', async () => {
  const user = userEvent.setup();
  const { router } = mount('/hunts/ht_web');
  await heading('ht_web');
  const steps = screen.getAllByTestId('agent-step');
  expect(steps.map((step) => step.dataset.step)).toEqual(['1', '2']);
  // Excerpts are text in a monospace block; the URL is not turned into a link.
  expect(screen.getByText('3 events https://evil.example.com/shell').tagName).toBe('PRE');
  expect(region('룰 제안').getByRole('link', { name: 'rp_web_shell' })).toBeInTheDocument();
  await user.click(screen.getAllByRole('link', { name: 'in_web_campaign' })[0]);
  expect(router.state.location.pathname).toBe('/incidents/in_web_campaign');
});

it('shows "없음" for a hunt without evidence, techniques, steps or proposals', async () => {
  mount('/hunts/ht_baseline_quiet');
  await heading('ht_baseline_quiet');
  expect(screen.getByText('이상 없음')).toBeInTheDocument();
  expect(screen.getByText('Unknown')).toBeInTheDocument();
  expect(region('근거').getByText('없음')).toBeInTheDocument();
  expect(region('Agent Log').getByText('없음')).toBeInTheDocument();
  expect(region('룰 제안').getByText('없음')).toBeInTheDocument();
  expect(screen.queryByText(/사람 확인 필요/)).toBeNull();
});

it('shows a hunt lookup failure', async () => {
  mount('/hunts/ht_missing');
  expect(await screen.findByRole('alert')).toHaveTextContent('Object not found');
});
