import type { RouteObject } from 'react-router';
import { Shell } from './shell';
import { TicketsPage } from '../pages/tickets';
import { ReviewPage } from '../pages/review';

import { TicketDetailPage } from '../pages/ticket-detail';
import { IncidentsPage } from '../pages/incidents';
import { IncidentDetailPage } from '../pages/incident-detail';

// F1~F3 supply ticket and incident pages; later screens retain their reserved routes.
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
        ) : path === '/incidents' ? (
          <IncidentsPage />
        ) : path === '/incidents/:incident_id' ? (
          <IncidentDetailPage />
        ) : null,
    })),
  },
];
