import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { expect, it } from 'vitest';
import { routes } from './router';
import { Providers } from './providers';

it.each([
  '/',
  '/review',
  '/tickets',
  '/tickets/tk_sample',
  '/incidents',
  '/incidents/in_sample',
  '/cases',
  '/cases/cs_sample',
  '/hunts',
  '/hunts/ht_sample',
  '/rules',
  '/rules/rp_sample',
])('mounts the foundation at %s', (path) => {
  render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />
    </Providers>,
  );
  expect(screen.getByRole('main')).toBeInTheDocument();
});

it('switches and persists the light and dark themes', async () => {
  render(
    <Providers>
      <RouterProvider router={createMemoryRouter(routes)} />
    </Providers>,
  );
  await userEvent.click(screen.getByRole('button', { name: /다크 모드/ }));
  expect(document.documentElement).toHaveClass('dark');
  expect(localStorage.getItem('zero-ticket-theme')).toBe('dark');
  await userEvent.click(screen.getByRole('button', { name: /라이트 모드/ }));
  expect(document.documentElement).not.toHaveClass('dark');
});
