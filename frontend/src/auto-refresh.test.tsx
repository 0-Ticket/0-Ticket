import { afterEach, beforeEach, expect, test } from "vitest";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import seed from "../../tests/fixtures/api/ui_seed.json";
import { dashboard, server, show } from "./test-utils";

type Call = { path: string; auto: string | null };
const calls: Call[] = [];
const log = ({ request }: { request: Request }) => {
  if (request.method === "GET")
    calls.push({
      path: new URL(request.url).pathname.replace("/api/", ""),
      auto: request.headers.get("x-auto-refresh"),
    });
};
beforeEach(() => server.events.on("request:start", log));
afterEach(() => {
  server.events.removeListener("request:start", log);
  calls.length = 0;
});
const paths = (from = 0) =>
  calls
    .slice(from)
    .map((c) => c.path)
    .sort();

// The timer is 10 s; "online" makes the same automatic read at once, so the tests need not wait.
async function refreshOnce() {
  const from = calls.length;
  act(() => void window.dispatchEvent(new Event("online")));
  await new Promise((done) => setTimeout(done, 80));
  return from;
}

const ticket = seed.tickets[0];
function serveTickets(nextCursor: string | null = null) {
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({
        items: [{ ...ticket, severity: 4, seed_source: null, incident: null }],
        next_cursor: nextCursor,
      }),
    ),
    http.get("*/api/tickets/:id", () =>
      HttpResponse.json({
        ticket,
        alerts: [],
        severity: 4,
        seed_source: null,
        incident: null,
      }),
    ),
  );
}

test("the first read and the reads the user starts carry no mark; the timer's read does", async () => {
  dashboard();
  show("/");
  await screen.findByText("Tickets by Risk Level");
  expect(calls.filter((c) => c.path === "dashboard")).toEqual([
    { path: "dashboard", auto: null },
  ]);
  const from = await refreshOnce();
  expect(calls.slice(from)).toEqual([{ path: "dashboard", auto: "1" }]);
});

test("the dashboard screen keeps one thing fresh, not the policy or me", async () => {
  dashboard();
  show("/");
  await screen.findByText("Tickets by Risk Level");
  await waitFor(() => expect(paths()).toContain("ticketing-policy"));
  const from = await refreshOnce();
  expect(paths(from)).toEqual(["dashboard"]);
});

test("a list keeps the chart numbers and the list fresh, and an open detail too: three reads, all marked", async () => {
  dashboard();
  serveTickets();
  show(`/tickets?selected=${ticket.id}`);
  await screen.findByRole("dialog");
  await waitFor(() => expect(paths()).toContain(`tickets/${ticket.id}`));
  await new Promise((done) => setTimeout(done, 50));
  const from = await refreshOnce();
  expect(paths(from)).toEqual(["dashboard", "tickets", `tickets/${ticket.id}`]);
  expect(calls.slice(from).every((c) => c.auto === "1")).toBe(true);
});

test("the next-page button does not flicker off while a refresh is in flight", async () => {
  dashboard();
  serveTickets("cursor-2");
  show("/tickets");
  const next = await screen.findByRole("button", { name: "다음 페이지" });
  await waitFor(() => expect(next).toBeEnabled());
  server.use(
    http.get("*/api/tickets", async () => {
      await delay(150);
      return HttpResponse.json({
        items: [{ ...ticket, severity: 4, seed_source: null, incident: null }],
        next_cursor: "cursor-2",
      });
    }),
  );
  act(() => void window.dispatchEvent(new Event("online")));
  await new Promise((done) => setTimeout(done, 40));
  expect(next).toBeEnabled();
  await new Promise((done) => setTimeout(done, 200));
});

test("a failed refresh keeps the numbers and says so; a 404 on refresh is an error screen as before", async () => {
  dashboard();
  show("/");
  await screen.findByText("Tickets by Risk Level");
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "db_unavailable" }, { status: 503 }),
    ),
  );
  await refreshOnce();
  expect(screen.getByText("Tickets by Risk Level")).toBeInTheDocument();
  expect(screen.getByText(/^갱신 실패 · 마지막 성공/)).toBeInTheDocument();
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "not_found" }, { status: 404 }),
    ),
  );
  await refreshOnce();
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.queryByText("Tickets by Risk Level")).toBeNull();
  // It stopped there: the screen's own retry button is what reads again, and that read has no mark.
  const from = await refreshOnce();
  expect(paths(from)).toEqual([]);
  dashboard();
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  await screen.findByText("Tickets by Risk Level");
  expect(calls.at(-1)).toEqual({ path: "dashboard", auto: null });
});

const incident = seed.incidents[1];
function serveIncident() {
  server.use(
    http.get("*/api/incidents/:id", () =>
      HttpResponse.json({
        incident,
        tickets: [],
        alerts: [],
        artifacts: [],
        proposals: [],
        ticket_graphs: [],
        seed_source: null,
      }),
    ),
  );
}

test("the incident page keeps only its own detail fresh, not the dashboard", async () => {
  dashboard();
  serveIncident();
  show(`/incidents/${incident.id}`);
  await screen.findByRole("heading", { level: 1, name: incident.title });
  const from = await refreshOnce();
  expect(calls.slice(from)).toEqual([
    { path: `incidents/${incident.id}`, auto: "1" },
  ]);
});

test("a hand-made sample answer and a screen with nothing to refresh are not read again", async () => {
  dashboard();
  show(`/incidents/${incident.id}?sample=graph`);
  await screen.findByRole("heading", { level: 1 });
  const from = await refreshOnce();
  expect(paths(from)).toEqual([]);
});
