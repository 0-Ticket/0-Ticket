import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it, vi } from 'vitest';
import { TestProviders as Providers } from '../test/providers';
import { routes } from './router';
import { Badge } from '../components/contract-display';

function mount(path: string) {
  return render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </Providers>,
  );
}

it('marks the active menu item in the main navigation', () => {
  mount('/tickets/tk_sample');
  const nav = within(screen.getByRole('navigation', { name: '주 메뉴' }));
  expect(nav.getAllByRole('link').map((link) => link.textContent)).toEqual([
    '대시보드',
    '검토 대기함',
    '전체 티켓',
    'Incident',
    'Case',
    '헌팅',
    '룰 제안',
  ]);
  expect(nav.getByRole('link', { name: '전체 티켓' })).toHaveAttribute('aria-current', 'page');
  expect(nav.getByRole('link', { name: '검토 대기함' })).not.toHaveAttribute('aria-current');
  expect(nav.getByRole('link', { name: '대시보드' })).not.toHaveAttribute('aria-current');
});

afterEach(() => {
  vi.restoreAllMocks();
});

// jsdom has no layout: place the menu strip at 375px with the Case link past its right edge.
function narrowMenu() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
    this: HTMLElement,
  ) {
    if (this.getAttribute('aria-label') === '주 메뉴') return new DOMRect(0, 0, 375, 52);
    if (this.textContent === 'Case') return new DOMRect(330, 8, 79, 36);
    return new DOMRect(0, 0, 60, 36);
  });
}

it('scrolls only the narrow menu strip to show the active link', () => {
  narrowMenu();
  const scroll = vi.spyOn(window, 'scrollTo');
  mount('/cases');
  const nav = screen.getByRole('navigation', { name: '주 메뉴' });
  expect(nav.scrollLeft).toBe(44);
  expect(scroll).not.toHaveBeenCalled();
});

it('keeps the narrow menu strip at the start on the dashboard and marks only it active', () => {
  narrowMenu();
  const scroll = vi.spyOn(window, 'scrollTo');
  mount('/');
  const nav = screen.getByRole('navigation', { name: '주 메뉴' });
  expect(nav.scrollLeft).toBe(0);
  expect(within(nav).getByRole('link', { name: '대시보드' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  expect(
    within(nav)
      .getAllByRole('link')
      .filter((link) => link.hasAttribute('aria-current')),
  ).toHaveLength(1);
  expect(scroll).not.toHaveBeenCalled();
});

it('scrolls the narrow menu strip to a link reached by keyboard', () => {
  narrowMenu();
  mount('/tickets');
  const nav = screen.getByRole('navigation', { name: '주 메뉴' });
  expect(nav.scrollLeft).toBe(0);
  within(nav).getByRole('link', { name: 'Case' }).focus();
  expect(nav.scrollLeft).toBe(44);
});

it.each([
  ['/review', '검토 대기함', '사람의 판단이 필요한 티켓입니다.'],
  ['/tickets', '전체 티켓', '상태와 관계없이 모든 티켓을 조회합니다.'],
])('states the purpose of %s in the page header', (path, title, purpose) => {
  mount(path);
  expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument();
  expect(screen.getByText(purpose, { exact: false })).toBeInTheDocument();
});

it.each([
  ['/tickets/tk_sample', '티켓 tk_sample', '티켓 목록', '/tickets'],
  ['/incidents/in_web_campaign', 'Incident in_web_campaign', 'Incident 목록', '/incidents'],
  ['/cases/cs_web_breach', 'Case cs_web_breach', 'Case 목록', '/cases'],
])('links %s back to its list from the breadcrumb', async (path, heading, label, href) => {
  mount(path);
  await screen.findByRole('heading', { name: heading }, { timeout: 3000 });
  const crumbs = within(screen.getByRole('navigation', { name: '위치' }));
  expect(crumbs.getByRole('link', { name: label })).toHaveAttribute('href', href);
});

it.each([
  ['/', '검토 지표'],
  ['/review', 'web-01'],
  ['/tickets/tk_sample', '티켓 tk_sample'],
  ['/incidents/in_web_campaign', 'Incident in_web_campaign'],
  ['/cases/cs_web_breach', '타임라인'],
])('never skips a heading level at %s', async (path, ready) => {
  const { container } = mount(path);
  await screen.findAllByText(ready, undefined, { timeout: 3000 });
  const levels = [...container.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((heading) =>
    Number(heading.tagName[1]),
  );
  expect(levels[0]).toBe(1);
  levels.forEach((level, index) => {
    if (index) expect(level - levels[index - 1]).toBeLessThanOrEqual(1);
  });
});

it('gives badges one tone per documented value and keeps unknown values as raw text', () => {
  render(
    <>
      <Badge value="awaiting_human" />
      <Badge value="tp" />
      <Badge value="example.unknown" />
      <Badge value={null} severity={5} />
      <Badge value={null} />
    </>,
  );
  expect(screen.getByText('검토 대기')).toHaveAttribute('data-tone', 'warning');
  expect(screen.getByText('TP')).toHaveAttribute('data-tone', 'critical');
  expect(screen.getByText('example.unknown')).toHaveAttribute('data-tone', 'neutral');
  expect(screen.getByText('Critical')).toHaveAttribute('data-tone', 'critical');
  expect(screen.getByText('없음')).toHaveAttribute('data-tone', 'neutral');
});
