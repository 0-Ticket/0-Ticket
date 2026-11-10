import { afterAll, afterEach, beforeAll, expect, test } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import seed from "../../tests/fixtures/api/ui_seed.json";
import sample from "../../tests/fixtures/frontend/json_viewer.json";
import App from "./App";

const server = setupServer();
const requests: URL[] = [];
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
function Where() {
  const location = useLocation();
  return (
    <output data-testid="where">{location.pathname + location.search}</output>
  );
}
function show(path: string) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
        <Where />
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
test("unknown-only ticket risk shows no count text", async () => {
  dashboard({ 0: 2, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0 });
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/tickets");
  expect(await screen.findByText("데이터 없음")).toBeInTheDocument();
  expect(screen.queryByText(/미상 \d+건/)).not.toBeInTheDocument();
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
  expect(screen.getByText(/실패 코드: schema_failed/)).toBeInTheDocument();
  expect(screen.getByText("정규화 결과 없음")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector('a[href="https://example.com"]')).toBeNull();
});
test("L3 ticket offers Hunt navigation, and filters reset cursor", async () => {
  dashboard();
  const ticket = seed.tickets[7];
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({
        items: [{ ...ticket, severity: 0, seed_source: "dev-seed-ui" }],
        next_cursor: ticket.id,
      }),
    ),
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
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("cursor"),
    ).toBe(ticket.id),
  );
  fireEvent.click(
    within(screen.getByRole("group", { name: "위험도 필터" })).getByRole(
      "button",
      { name: "미상" },
    ),
  );
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("severity"),
    ).toBe("0"),
  );
  const last = requests.filter((r) => r.pathname === "/api/tickets").at(-1);
  expect(last?.searchParams.has("cursor")).toBe(false);
  expect(screen.getByText(/^1\//)).toBeInTheDocument();
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
test("dashboard shows the design flow and keeps ticket total without removed texts", async () => {
  dashboard();
  show("/");
  const flow = await screen.findByRole("list", { name: "처리 흐름" });
  const stage4 = within(flow).getAllByRole("listitem")[3];
  expect(stage4).toHaveTextContent("Incident으로 묶이기");
  expect(stage4).toHaveTextContent("3");
  expect(screen.getByText("전체 8건")).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "분석 결과가 있는 Incident" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /집계 새로고침/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText(/전체 보관 자료|개발 시드/),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/최신순|페이지당/)).not.toBeInTheDocument();
});

test("hunts overview uses a slash and drops status counts and promotion ratio", async () => {
  dashboard();
  server.use(
    http.get("*/api/hunts", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/hunts");
  expect(
    await screen.findByRole("heading", {
      name: "전체 가설 5건 / Ticket 승격 1건",
    }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/승격 비율/)).not.toBeInTheDocument();
  expect(screen.queryByText(/대기 1건/)).not.toBeInTheDocument();
});
test("JSON field table and raw JSON keep external strings as text", async () => {
  dashboard();
  server.use(
    http.get("*/api/events", () =>
      HttpResponse.json({
        items: [
          {
            raw_id: sample.id,
            record_id: null,
            normalize_status: "pending",
            error_code: null,
            title: null,
            severity: null,
            seed_source: null,
            fetched_at: sample.fetched_at,
          },
        ],
        next_cursor: null,
      }),
    ),
    http.get("*/api/events/:id", () =>
      HttpResponse.json({
        raw_record: sample,
        record: null,
        normalize_status: "pending",
        error_code: null,
        seed_source: null,
      }),
    ),
  );
  const { container } = show(`/events?selected=${sample.id}`);
  const dialog = await screen.findByRole("dialog");
  expect(
    await within(dialog).findByText(sample.original.message),
  ).toBeInTheDocument();
  expect(within(dialog).getByText("original.<b>key</b>")).toBeInTheDocument();
  expect(within(dialog).getByText("T1190, T1059")).toBeInTheDocument();
  expect(dialog.querySelector("img, b, strong, script")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "원본 JSON" }));
  expect(within(dialog).getByText(/"<b>key<\/b>": "값"/)).toBeInTheDocument();
  expect(dialog.querySelector("img, b, strong, script")).toBeNull();
  expect(container.querySelector('a[href^="https://example.com"]')).toBeNull();
});
test("previous page returns through the cursor trail", async () => {
  dashboard();
  const items = seed.incidents.map((i) => ({
    ...i,
    display_severity: i.severity,
    seed_source: "dev-seed-ui",
  }));
  server.use(
    http.get("*/api/incidents", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      const index = cursor ? items.findIndex((i) => i.id === cursor) + 1 : 0;
      return HttpResponse.json({
        items: items.slice(index, index + 1),
        next_cursor: index + 1 < items.length ? items[index].id : null,
      });
    }),
  );
  show("/incidents");
  expect(await screen.findByText(items[0].id)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이전 페이지" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  expect(await screen.findByText(items[1].id)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  expect(await screen.findByText(items[2].id)).toBeInTheDocument();
  expect(screen.getByText(/^3\//)).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
  expect(await screen.findByText(items[1].id)).toBeInTheDocument();
  expect(screen.getByText(/^2\//)).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
  expect(await screen.findByText(items[0].id)).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/incidents$/);
});
test("ticket origin and case status filters are kept as chips", async () => {
  dashboard();
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get("*/api/cases", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/tickets");
  fireEvent.click(
    within(await screen.findByRole("group", { name: "출처 필터" })).getByRole(
      "button",
      { name: "l3" },
    ),
  );
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("origin"),
    ).toBe("l3"),
  );
  const chip = within(
    screen.getByRole("group", { name: "출처 필터" }),
  ).getByRole("button", { name: "l3" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(chip);
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.has("origin"),
    ).toBe(false),
  );
  fireEvent.click(screen.getByRole("link", { name: /Case/ }));
  expect(
    await screen.findByRole("group", { name: "상태 필터" }),
  ).toHaveTextContent("해결됨");
});
test("profile text and settings button make no request or navigation", async () => {
  dashboard();
  show("/");
  await screen.findByRole("list", { name: "처리 흐름" });
  expect(screen.getByText("관리자")).toBeInTheDocument();
  const before = requests.length;
  fireEvent.click(screen.getByRole("button", { name: "설정" }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(requests.length).toBe(before);
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
});

test("normalization includes pending in total and shows no success rate", async () => {
  dashboard();
  server.use(
    http.get("*/api/alerts", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/alerts");
  const card = (
    await screen.findByRole("heading", { name: "Alert 정규화 현황" })
  ).closest("article")!;
  expect(within(card).getByText("9건")).toBeInTheDocument();
  expect(within(card).getByText("7건")).toBeInTheDocument();
  expect(within(card).queryByText(/성공률/)).not.toBeInTheDocument();
});

test("cursor URL restores the previous page and filters clear its trail", async () => {
  dashboard();
  const first = seed.tickets[0].id;
  const second = seed.tickets[1].id;
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: second }),
    ),
  );
  show(`/tickets?origin=l3&cursor=${second}&trail=&trail=${first}`);
  await screen.findByText("조건에 맞는 데이터가 없습니다.");
  expect(screen.getByText(/^3\//)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("cursor"),
    ).toBe(first),
  );
  expect(screen.getByTestId("where")).toHaveTextContent("origin=l3");
  fireEvent.click(
    within(screen.getByRole("group", { name: "상태 필터" })).getByRole(
      "button",
      { name: "L2 대기" },
    ),
  );
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("status"),
    ).toBe("escalated"),
  );
  expect(screen.getByTestId("where").textContent).not.toMatch(
    /cursor|trail|selected/,
  );
});

test("legacy cursor links can advance and return without losing the starting cursor", async () => {
  dashboard();
  const first = seed.tickets[0].id;
  const second = seed.tickets[1].id;
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: second }),
    ),
  );
  show(`/tickets?cursor=${first}`);
  await screen.findByText("조건에 맞는 데이터가 없습니다.");
  expect(screen.getByText(/^2\//)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/tickets")
        .at(-1)
        ?.searchParams.get("cursor"),
    ).toBe(second),
  );
  expect(screen.getByText(/^3\//)).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
  expect(screen.getByTestId("where")).toHaveTextContent(`cursor=${first}`);
  expect(screen.getByText(/^2\//)).toBeInTheDocument();
});

for (const resource of ["alerts", "events"] as const) {
  test(`${resource} successful detail preserves normalized and raw fields`, async () => {
    dashboard();
    const record = seed[resource][0];
    const raw = seed.raw_records.find((r) => r.id === record.raw_id)!;
    server.use(
      http.get(`*/api/${resource}`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(`*/api/${resource}/:id`, () =>
        HttpResponse.json({
          raw_record: raw,
          record,
          normalize_status: "succeeded",
          error_code: null,
          seed_source: "dev-seed-ui",
        }),
      ),
    );
    show(`/${resource}?selected=${raw.id}`);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(record.id)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("heading", { name: "정규화 결과 · OCSF" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("heading", { name: "수집 원본" }),
    ).toBeInTheDocument();
    expect(within(dialog).getAllByRole("table")).toHaveLength(2);
    fireEvent.click(within(dialog).getByRole("button", { name: "상세 닫기" }));
    expect(screen.getByTestId("where").textContent).not.toContain("selected");
  });
}

test("Incident reports and response proposals remain text and link to source Tickets", async () => {
  dashboard();
  const incident = seed.incidents[1];
  const artifact = seed.incident_artifacts[0];
  server.use(
    http.get("*/api/incidents", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get("*/api/incidents/:id", () =>
      HttpResponse.json({
        incident,
        artifacts: [artifact],
        proposals: [
          {
            ...seed.incident_proposals[0],
            kind: "response_action",
            body: sample.original.message,
          },
        ],
        seed_source: "dev-seed-ui",
      }),
    ),
  );
  show(`/incidents?selected=${incident.id}`);
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("대응 방안 제안")).toBeInTheDocument();
  expect(within(dialog).getByText(sample.original.message)).toBeInTheDocument();
  expect(dialog.querySelector("img, script")).toBeNull();
  expect(
    within(dialog).getByRole("link", { name: "원본 Ticket 1" }),
  ).toHaveAttribute("href", `/tickets?selected=${incident.ticket_ids[0]}`);
  expect(
    within(dialog).getByRole("heading", { name: "분석 라운드 1" }),
  ).toBeInTheDocument();
});

test("Case detail links to the Incident and status chips filter requests", async () => {
  dashboard();
  const item = seed.cases[0];
  server.use(
    http.get("*/api/cases", () =>
      HttpResponse.json({ items: [item], next_cursor: null }),
    ),
    http.get("*/api/cases/:id", () =>
      HttpResponse.json({ case: item, seed_source: "dev-seed-ui" }),
    ),
  );
  show("/cases");
  fireEvent.click(await screen.findByRole("button", { name: item.title }));
  expect(
    await screen.findByRole("link", { name: "원본 Incident" }),
  ).toHaveAttribute("href", `/incidents?selected=${item.incident_id}`);
  fireEvent.click(screen.getByRole("button", { name: "상세 닫기" }));
  fireEvent.click(
    within(screen.getByRole("group", { name: "상태 필터" })).getByRole(
      "button",
      { name: "해결됨" },
    ),
  );
  await waitFor(() =>
    expect(
      requests
        .filter((r) => r.pathname === "/api/cases")
        .at(-1)
        ?.searchParams.get("status"),
    ).toBe("resolved"),
  );
});

test("Hunt runs, techniques and promoted Ticket navigation are preserved", async () => {
  dashboard();
  const hunt = seed.hunts[1];
  const log = seed.agent_logs[0];
  server.use(
    http.get("*/api/hunts", () =>
      HttpResponse.json({ items: [hunt], next_cursor: null }),
    ),
    http.get("*/api/hunts/:id", () =>
      HttpResponse.json({
        hunt,
        ticket_id: seed.tickets[7].id,
        techniques: [{ id: "T1190", name: sample.original.message }],
        runs: [
          {
            run_id: log.run_id,
            task: "l3_verify",
            attempt: 1,
            outcome: log.outcome,
            failure: null,
            tokens_in: log.tokens_in,
            tokens_out: log.tokens_out,
            started_at: log.started_at,
            duration_ms: log.duration_ms,
          },
        ],
      }),
    ),
  );
  show("/hunts");
  fireEvent.click(await screen.findByRole("button", { name: hunt.hypothesis }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText(log.run_id)).toBeInTheDocument();
  expect(within(dialog).getByText(sample.original.message)).toBeInTheDocument();
  expect(dialog.querySelector("img, script")).toBeNull();
  expect(
    within(dialog).getByRole("link", { name: "승격 Ticket" }),
  ).toHaveAttribute("href", `/tickets?selected=${seed.tickets[7].id}`);
});

test("page indicator shows the maximum from dashboard counts, or - when filtered by severity", async () => {
  dashboard();
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({
        flow: { tickets: 60 },
        ticket_status: { new: 30, linked: 30 },
        ticket_severity: {},
        incident_status: {},
        case_status: {},
        normalization: {
          alert: { succeeded: 0, failed: 0, pending: 0, success_ratio: null },
          event: { succeeded: 0, failed: 0, pending: 0, success_ratio: null },
        },
        hunting: { statuses: {}, total: 0, promoted: 0, promotion_ratio: null },
        analyzed_incidents: [],
        top_incidents: [],
      }),
    ),
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/tickets");
  expect(await screen.findByText("1/3")).toBeInTheDocument();
  fireEvent.click(
    within(screen.getByRole("group", { name: "상태 필터" })).getByRole(
      "button",
      { name: "L1 대기" },
    ),
  );
  expect(await screen.findByText("1/2")).toBeInTheDocument();
  fireEvent.click(
    within(screen.getByRole("group", { name: "위험도 필터" })).getByRole(
      "button",
      { name: "미상" },
    ),
  );
  expect(await screen.findByText("1/-")).toBeInTheDocument();
});
