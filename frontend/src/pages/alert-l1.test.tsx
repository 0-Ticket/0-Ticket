import { createTestQueryClient } from '../test/query-clients';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { expect, it } from 'vitest';
import { routes } from '../app/router';
import { ThemeProvider } from '../lib/theme';
import { server } from '../mocks/server';
import untrusted from '../../../tests/fixtures/frontend/untrusted-text.json';

function mount(path: string) {
  const client = createTestQueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 1000 } },
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

it('shows the branch, decisions, evidence request failures and the agent log of a held alert', async () => {
  const requests: string[] = [];
  const listener = ({ request }: { request: Request }) =>
    requests.push(`${request.method} ${new URL(request.url).pathname}`);
  server.events.on('request:start', listener);
  try {
    const user = userEvent.setup();
    const { container } = mount('/alerts/al_held');
    // First MSW -> Query -> render of this page exceeded the 1s default under heavy CPU load.
    await screen.findByText('알럿 al_held', { selector: 'h1' }, { timeout: 3000 });
    const crumbs = within(screen.getByRole('navigation', { name: '위치' }));
    expect(crumbs.getByRole('link', { name: 'L1 결과 조회' })).toHaveAttribute('href', '/review');
    // C21: the path the alert took and what the branch matched on.
    const branch = within(screen.getByRole('region', { name: '분기 경로' }));
    expect(branch.getByText('L1 엔티티 조회')).toBeInTheDocument();
    expect(branch.getByText(/198\.51\.100\.23/)).toBeInTheDocument();
    expect(branch.getByText(/규칙: 없음/)).toBeInTheDocument();
    // C23: this alert was held twice, newest first, with each reason named.
    const decisions = within(screen.getByRole('region', { name: 'L1 결정' }));
    expect(decisions.getAllByRole('listitem')).toHaveLength(2);
    expect(decisions.getByText('증거 요청 실패')).toBeInTheDocument();
    expect(decisions.getByText('확신도 미만')).toBeInTheDocument();
    expect(decisions.getByText(/0\.41/)).toBeInTheDocument();
    // C22: the failed request is the evidence collection failure (D-034).
    const evidence = within(screen.getByRole('region', { name: '증거 요청' }));
    expect(evidence.getAllByRole('listitem')).toHaveLength(3);
    expect(evidence.getByText('실패')).toBeInTheDocument();
    expect(evidence.getAllByText('완료')).toHaveLength(2);
    expect(evidence.getByText(/재시도 3회/)).toBeInTheDocument();
    expect(evidence.getByText(/siem query timed out/)).toHaveTextContent(untrusted.summary);
    await user.click(evidence.getAllByText('요청·결과 상세')[0]);
    expect(evidence.getByText('unknown-host')).toBeInTheDocument();
    // C8: the alert-level agent log, excerpts folded away and never parsed.
    expect(screen.getAllByTestId('agent-step').map((x) => x.getAttribute('data-step'))).toEqual([
      '1',
      '2',
    ]);
    for (const summary of screen.getAllByText(/입력·출력 발췌/)) await user.click(summary);
    expect(screen.getByText(untrusted.input_excerpt)).toBeInTheDocument();
    expect(screen.getByText(untrusted.output_excerpt)).toBeInTheDocument();
    // Lookup fields of the alert itself, with the unknown source asset named as such.
    expect(screen.getByText('자산 정보 없음')).toBeInTheDocument();
    expect(screen.getByText('web-02')).toBeInTheDocument();
    expect(container.querySelector('img, script, iframe, b')).toBeNull();
    expect(container.querySelector('a[href^="https:"]')).toBeNull();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /동의|뒤집기|승인|반려/ })).not.toBeInTheDocument();
    await waitFor(() => expect(requests).toEqual(['GET /api/alerts/al_held/l1']));
    for (const time of container.querySelectorAll('time')) {
      expect(time).toHaveTextContent(new Date(Number(time.title)).toLocaleString());
    }
  } finally {
    server.events.removeListener('request:start', listener);
  }
});

it('reads an alert that has no branch or decision yet as an empty result, not an error', async () => {
  mount('/alerts/al_sample');
  await screen.findByText('알럿 al_sample', { selector: 'h1' }, { timeout: 3000 });
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByText('분기 기록이 없습니다.')).toBeInTheDocument();
  expect(screen.getByText('L1 결정이 없습니다.')).toBeInTheDocument();
  expect(screen.getByText('증거 요청이 없습니다.')).toBeInTheDocument();
  expect(screen.queryAllByTestId('agent-step')).toHaveLength(0);
});

it('reports a missing alert as an error with a retry', async () => {
  mount('/alerts/al_missing');
  const error = await screen.findByRole('alert', undefined, { timeout: 3000 });
  expect(error).toHaveTextContent('Object not found');
  expect(screen.queryByText('알럿 al_missing', { selector: 'h1' })).not.toBeInTheDocument();
  expect(within(error).getByRole('button', { name: '다시 시도' })).toBeInTheDocument();
});
