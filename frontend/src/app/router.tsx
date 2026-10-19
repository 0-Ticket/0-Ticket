import type { RouteObject } from 'react-router';
import { Shell } from './shell';
import { TicketsPage } from '../pages/tickets';
import { L1ResultsPage } from '../pages/l1-results';
import { AlertL1Page } from '../pages/alert-l1';
import { DashboardPage } from '../pages/dashboard';
import { TicketDetailPage } from '../pages/ticket-detail';
import { IncidentsPage } from '../pages/incidents';
import { IncidentDetailPage } from '../pages/incident-detail';
import { CasesPage } from '../pages/cases';
import { CaseDetailPage } from '../pages/case-detail';
import { HuntsPage } from '../pages/hunts';
import { HuntDetailPage } from '../pages/hunt-detail';
import { RulesPage } from '../pages/rules';
import { RuleDetailPage } from '../pages/rule-detail';

// F1 serves the read-only L1 results at `/review` and one alert at `/alerts/:alert_id` (box 27);
// F2~F5 supply ticket, incident, case, hunt and rule pages; F6 is the dashboard at `/`.
export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      '/',
      '/review',
      '/tickets',
      '/tickets/:ticket_id',
      '/alerts/:alert_id',
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
        path === '/' ? (
          <DashboardPage />
        ) : path === '/review' ? (
          <L1ResultsPage />
        ) : path === '/tickets' ? (
          <TicketsPage />
        ) : path === '/tickets/:ticket_id' ? (
          <TicketDetailPage />
        ) : path === '/alerts/:alert_id' ? (
          <AlertL1Page />
        ) : path === '/incidents' ? (
          <IncidentsPage />
        ) : path === '/incidents/:incident_id' ? (
          <IncidentDetailPage />
        ) : path === '/cases' ? (
          <CasesPage />
        ) : path === '/cases/:case_id' ? (
          <CaseDetailPage />
        ) : path === '/hunts' ? (
          <HuntsPage />
        ) : path === '/hunts/:hunt_id' ? (
          <HuntDetailPage />
        ) : path === '/rules' ? (
          <RulesPage />
        ) : path === '/rules/:proposal_id' ? (
          <RuleDetailPage />
        ) : null,
    })),
  },
];
