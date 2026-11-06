import { afterAll, afterEach, beforeAll, expect, test } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import seed from "../../tests/fixtures/api/ui_seed.json";
import App from "./App";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
function show(path: string) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
function dashboard(
  ticketSeverity = { 0: 2, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1 },
) {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({
        flow: { tickets: 8, incidents: 5, cases: 1 },
        ticket_severity: ticketSeverity,
        ticket_status: { new: 1 },
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
        analyzed_incidents: [],
        top_incidents: [],
      }),
    ),
  );
}
test("unknown-only ticket risk is shown instead of an empty dataset", async () => {
  dashboard({ 0: 2, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 });
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/tickets");
  expect(
    await screen.findByText(/알려진 위험도 없음 · 미상 2건/),
  ).toBeInTheDocument();
});
test("Case waiting tab explicitly shows Incidents and disables decisions", async () => {
  dashboard();
  let requestStatus = "";
  server.use(
    http.get("*/api/incidents", ({ request }) => {
      requestStatus = new URL(request.url).searchParams.get("status") ?? "";
      return HttpResponse.json({
        items: [
          {
            ...seed.incidents[1],
            display_severity: 5,
            seed_source: "dev-seed-ui",
          },
        ],
        next_cursor: null,
      });
    }),
    http.get("*/api/incidents/:id", () =>
      HttpResponse.json({
        incident: seed.incidents[1],
        artifacts: [],
        proposals: [],
        seed_source: "dev-seed-ui",
      }),
    ),
  );
  show("/cases?tab=waiting");
  expect(await screen.findByText(seed.incidents[1].title)).toBeInTheDocument();
  expect(requestStatus).toBe("awaiting_review");
  expect(screen.getByText(/아직 Case가 아닌/)).toBeInTheDocument();
  fireEvent.click(screen.getByText(seed.incidents[1].title));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "승인" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "반려" })).toBeDisabled();
});
test("untrusted raw text remains text, with no executable element or external link", async () => {
  dashboard();
  const raw = seed.raw_records.find((r) => r.original.message)!;
  server.use(
    http.get("*/api/alerts", () =>
      HttpResponse.json({
        items: [
          {
            raw_id: raw.id,
            record_id: null,
            normalize_status: "failed",
            error_code: "schema_failed",
            title: null,
            severity: null,
            seed_source: "dev-seed-ui",
            fetched_at: raw.fetched_at,
          },
        ],
        next_cursor: null,
      }),
    ),
    http.get("*/api/alerts/:id", () =>
      HttpResponse.json({
        raw_record: raw,
        record: null,
        normalize_status: "failed",
        error_code: "schema_failed",
        seed_source: "dev-seed-ui",
      }),
    ),
  );
  const { container } = show("/alerts");
  fireEvent.click(await screen.findByRole("button", { name: /원본/ }));
  expect(
    await screen.findByText(/<script>alert\(1\)<\/script>/),
  ).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector('a[href="https://example.com"]')).toBeNull();
});
test("L3 ticket offers Hunt navigation, and filters reset cursor", async () => {
  dashboard();
  const ticket = seed.tickets[7];
  const requests: URL[] = [];
  server.use(
    http.get("*/api/tickets", ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json({
        items: [{ ...ticket, severity: 0, seed_source: "dev-seed-ui" }],
        next_cursor: ticket.id,
      });
    }),
    http.get("*/api/tickets/:id", () =>
      HttpResponse.json({ ticket, severity: 0, seed_source: "dev-seed-ui" }),
    ),
  );
  show("/tickets");
  fireEvent.click(await screen.findByRole("button", { name: /tkt_/ }));
  expect(
    await screen.findByRole("link", { name: "원본 Hunt" }),
  ).toHaveAttribute("href", `/hunts?selected=${ticket.hunt_id}`);
  fireEvent.click(screen.getByRole("button", { name: "상세 닫기" }));
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() =>
    expect(requests.at(-1)?.searchParams.get("cursor")).toBe(ticket.id),
  );
  fireEvent.change(screen.getByLabelText("위험도 필터"), {
    target: { value: "0" },
  });
  await waitFor(() =>
    expect(requests.at(-1)?.searchParams.get("severity")).toBe("0"),
  );
  expect(requests.at(-1)?.searchParams.has("cursor")).toBe(false);
});
test("error retries and empty data are distinct", async () => {
  dashboard();
  let count = 0;
  server.use(
    http.get("*/api/hunts", () => {
      count++;
      return count === 1
        ? HttpResponse.json({ error: "db_unavailable" }, { status: 503 })
        : HttpResponse.json({ items: [], next_cursor: null });
    }),
  );
  show("/hunts");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "불러오지 못했습니다",
  );
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(
    await screen.findByText("조건에 맞는 데이터가 없습니다."),
  ).toBeInTheDocument();
});
