import type { RouteObject } from 'react-router';
import { Shell } from './shell';

// F0 reserves URLs only; F1–F6 supply page content in subsequent issues.
export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      '/',
      '/review',
      '/tickets',
      '/tickets/:ticket_id',
      '/incidents',
      '/incidents/:incident_id',
      '/cases',
      '/cases/:case_id',
      '/hunts',
      '/hunts/:hunt_id',
      '/rules',
      '/rules/:proposal_id',
    ].map((path) => ({ path, element: null })),
  },
];
