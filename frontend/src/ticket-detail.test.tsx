import { expect, test } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import seed from "../../tests/fixtures/api/ui_seed.json";
import { dashboard, requests, server, show } from "./test-utils";

const ticket = seed.tickets[0];
const alerts = [
  {
    id: "alt_01a19f93-1266-7000-8000-000000000101",
    title: "web-01 로그인 경로 SQL 인젝션 패턴 탐지",
    time: 1793678581000,
    severity: 4,
  },
  {
    id: "alt_01a19f93-1266-7000-8000-000000000102",
    title: "<b>비정상</b> 응답 크기",
    time: 1793678701000,
    severity: 0,
  },
];
const verdict = {
  decision: "malicious",
  confidence: 0.92,
  reason: "SQL 인젝션이 반복됐다 <script>x</script>",
  evidence_ids: [alerts[0].id, "agl_01a19f93-1266-7000-8000-0000000000c1"],
  decided_at: 1793678700000,
};
const linked = {
  id: seed.incidents[0].id,
  title: seed.incidents[0].title,
  status: "awaiting_review",
  severity: 4,
  assessed_severity: 4,
  display_severity: 4,
};

function serve(body: Record<string, unknown>) {
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({
        items: [{ ...ticket, severity: 4, seed_source: null, incident: null }],
        next_cursor: null,
      }),
    ),
    http.get("*/api/tickets/:id", () =>
      HttpResponse.json({
        ticket,
        alerts,
        severity: 4,
        seed_source: null,
        incident: null,
        ...body,
      }),
    ),
  );
}
async function open() {
  show("/tickets");
  fireEvent.click(await screen.findByRole("button", { name: ticket.title }));
  return await screen.findByRole("dialog");
}

test("the original alert summaries come with the ticket, in one request", async () => {
  dashboard();
  serve({});
  const dialog = await open();
  expect(await within(dialog).findByText(alerts[0].title)).toBeInTheDocument();
  expect(dialog).toHaveTextContent("원본 Alert");
  expect(dialog).toHaveTextContent("2건");
  expect(dialog).toHaveTextContent(alerts[0].id);
  expect(dialog).toHaveTextContent("4 Level");
  expect(dialog).toHaveTextContent("미상");
  const links = within(dialog).getAllByRole("link", { name: /상세 보기/ });
  expect(links.map((a) => a.getAttribute("href"))).toEqual(
    alerts.map((a) => `/alerts?selected=${a.id}`),
  );
  expect(
    requests.filter((r) => r.pathname.startsWith("/api/alerts/")),
  ).toHaveLength(0);
  expect(
    requests.filter((r) => r.pathname === `/api/tickets/${ticket.id}`),
  ).toHaveLength(1);
});

test("alert summary titles are shown as text", async () => {
  dashboard();
  serve({});
  const dialog = await open();
  expect(
    await within(dialog).findByText("<b>비정상</b> 응답 크기"),
  ).toBeInTheDocument();
  expect(dialog.querySelector("b")).toBeNull();
});

test("a ticket with no alert summaries (an L3 ticket) shows no alert section", async () => {
  dashboard();
  serve({ alerts: [] });
  const dialog = await open();
  await within(dialog).findByText("Ticket 판정과 근거");
  expect(dialog).not.toHaveTextContent("원본 Alert");
});

test("the linked incident is shown with its title, status, severity and a link", async () => {
  dashboard();
  serve({ incident: linked });
  const dialog = await open();
  expect(
    await within(dialog).findByText("연결된 Incident"),
  ).toBeInTheDocument();
  expect(dialog).toHaveTextContent(linked.title);
  expect(dialog).toHaveTextContent("승인 대기");
  expect(
    within(dialog).getByRole("link", { name: "Incident 보기" }),
  ).toHaveAttribute("href", `/incidents?selected=${linked.id}`);
});

test("a ticket with no incident has no linked incident card", async () => {
  dashboard();
  serve({});
  const dialog = await open();
  await within(dialog).findByText("Ticket 판정과 근거");
  expect(dialog).not.toHaveTextContent("연결된 Incident");
});

test("the verdict review shows only what the verdict contract has", async () => {
  dashboard();
  serve({ ticket: { ...ticket, verdict } });
  const dialog = await open();
  expect(await within(dialog).findByText("근거 검토")).toBeInTheDocument();
  expect(dialog).toHaveTextContent("최종 판정 · MALICIOUS");
  expect(dialog).toHaveTextContent("신뢰도 92%");
  expect(dialog).toHaveTextContent("SQL 인젝션이 반복됐다 <script>x</script>");
  for (const id of verdict.evidence_ids) expect(dialog).toHaveTextContent(id);
  for (const absent of ["신호 일치", "강한 근거", "보조 근거"])
    expect(dialog).not.toHaveTextContent(absent);
  expect(dialog.querySelector("script")).toBeNull();
});

test("an undecided ticket says it has no verdict yet", async () => {
  dashboard();
  serve({ ticket: { ...ticket, verdict: null } });
  const dialog = await open();
  expect(
    await within(dialog).findByText("아직 판정되지 않았어요."),
  ).toBeInTheDocument();
  expect(dialog).not.toHaveTextContent("근거 검토");
});

test("the ticket history shows when it was created and last updated", async () => {
  dashboard();
  serve({});
  const dialog = await open();
  expect(await within(dialog).findByText("Ticket 이력")).toBeInTheDocument();
  expect(dialog).toHaveTextContent("생성");
  expect(dialog).toHaveTextContent("마지막 갱신");
});
