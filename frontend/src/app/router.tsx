import type { RouteObject } from 'react-router';
import { Shell } from './shell';
import { TicketsPage } from '../pages/tickets';
import { ReviewPage } from '../pages/review';

// F1/F2 supply ticket pages; later screens retain their reserved routes.
import { TicketDetailPage } from '../pages/ticket-detail';
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
    ].map((path) => ({
      path,
      element:
        path === '/review' ? (
          <ReviewPage />
        ) : path === '/tickets' ? (
          <TicketsPage />
        ) : path === '/tickets/:ticket_id' ? (
          <TicketDetailPage />
        ) : null,
    })),
  },
];
