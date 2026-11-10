import { afterAll, afterEach, beforeAll } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import auth from "../../tests/fixtures/frontend/auth.json";
import seed from "../../tests/fixtures/api/ui_seed.json";
import App from "./App";
import { createQueryClient } from "./api/query-client";
import { Where } from "./where";

export { auth };
export const adminMe = auth.admin;
// The default handler survives resetHandlers; tests override it with server.use.
export const server = setupServer(
  http.get("*/api/auth/me", () => HttpResponse.json(adminMe)),
  // The dashboard reads the policy mode to pick the 6- or 7-stage flow; auto unless a test says otherwise.
  http.get("*/api/ticketing-policy", () =>
    HttpResponse.json({ mode: "auto", scenario_rule_ids: [] }),
  ),
);
export const requests: URL[] = [];
beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  server.events.on("request:start", ({ request }) =>
    requests.push(new URL(request.url)),
  );
});
afterEach(() => {
  server.resetHandlers();
  requests.length = 0;
});
afterAll(() => server.close());
export function show(path: string) {
  const client = createQueryClient();
  // Production keeps data fresh for 30 s; tests count requests, so every read is fresh.
  client.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
export function dashboard(
  ticketSeverity = { 0: 2, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1 },
) {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({
        flow: {
          normalization_pending: 2,
          l1_alerts_pending: 1,
          l1_tickets_pending: 1,
          tickets: 8,
          incidents: 5,
          cases: 1,
        },
        ticket_severity: ticketSeverity,
        ticket_status: {
          new: 1,
          held: 0,
          closed: 0,
          escalated: 3,
          linked: 4,
        },
        incident_status: { awaiting_review: 1 },
        case_status: { open: 1 },
        normalization: {
          alert: { succeeded: 7, failed: 1, pending: 1, success_ratio: 0.875 },
          event: { succeeded: 1, failed: 1, pending: 1, success_ratio: 0.5 },
        },
        hunting: {
          statuses: { pending: 1, confirmed: 1 },
          total: 5,
          promoted: 1,
          promotion_ratio: 0.2,
        },
        analyzed_incidents: [
          {
            ...seed.incidents[1],
            display_severity: 5,
            seed_source: "dev-seed-ui",
          },
        ],
        top_incidents: [],
      }),
    ),
  );
}
