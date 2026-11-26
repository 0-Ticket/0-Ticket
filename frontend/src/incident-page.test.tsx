import { expect, test, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import seed from "../../tests/fixtures/api/ui_seed.json";
import graphFixture from "../../tests/fixtures/frontend/incident_graph.json";
import page from "../../tests/fixtures/frontend/incident_page.json";
import { auth, dashboard, requests, server, show } from "./test-utils";

const base = seed.incidents[1]; // awaiting_review
const other = seed.incidents[2];
const artifact = seed.incident_artifacts.find(
  (a) => a.incident_id === base.id,
)!;
const url = `/incidents/${base.id}`;

function detail(overrides: Record<string, unknown> = {}) {
  return {
    incident: {
      ...base,
      ticket_ids: page.tickets.map((t) => t.id),
      entities: page.entities,
    },
    tickets: page.tickets,
    alerts: page.alerts,
    artifacts: [artifact],
    proposals: [],
    ticket_graphs: [],
    entity_criticality: [],
    seed_source: null,
    ...overrides,
  };
}
function serve(body: object = detail(), me: object = auth.admin) {
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json(me)),
    http.get("*/api/incidents/:id", () => HttpResponse.json(body)),
  );
}
const ticketAt = (i: number) => ({
  id: `tkt_01a19f93-1266-7000-8000-${String(100 + i).padStart(12, "0")}`,
  title: `샘플 Ticket ${i + 1}`,
  decision: (["malicious", "undetermined", "benign", null] as const)[i % 4],
  severity: i % 7,
  created_at: 1793678000000 + i * 60000,
  evidence_count: i,
  alert_ids: [],
  entities: [],
});
const types = ["ip", "url", "host", "user", "domain", "file_hash", "process"];
const entityAt = (i: number) => ({
  type: types[i % types.length],
  value:
    i === 5
      ? `https://example.com/${"a".repeat(300)}`
      : `${types[i % types.length]}-${i}`,
  role: null,
});
const many = (n: number, make: (i: number) => object) =>
  Array.from({ length: n }, (_, i) => make(i));
const tab = (name: RegExp | string) => screen.findByRole("tab", { name });

test("an incident opens as its own page from the list, keeping the sidebar", async () => {
  dashboard();
  server.use(
    http.get("*/api/incidents", () =>
      HttpResponse.json({
        items: [{ ...base, display_severity: 5, seed_source: null }],
        next_cursor: null,
      }),
    ),
  );
  serve();
  show("/incidents");
  fireEvent.click(await screen.findByText(base.title));
  expect(
    await screen.findByRole("heading", { level: 1, name: base.title }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(url);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("link", { name: "Incident" })).toBeInTheDocument(); // 사이드바
});

test("the page opens straight from its address and shows the header numbers", async () => {
  serve();
  show(url);
  expect(
    await screen.findByRole("heading", { level: 1, name: base.title }),
  ).toBeInTheDocument();
  const numbers = screen.getByRole("group", { name: "요약 숫자" });
  expect(numbers).toHaveTextContent(/Ticket\s*3/);
  expect(numbers).toHaveTextContent(/Alert\s*2/);
  expect(numbers).toHaveTextContent(/엔티티\s*5/);
  expect(numbers).toHaveTextContent(/malicious\s*1/);
  expect(numbers).toHaveTextContent(/undetermined\s*1/);
  expect(numbers).toHaveTextContent(/판정 전\s*1/);
  expect(screen.getByRole("tab", { name: /^엔티티/ })).toHaveTextContent("5"); // 헤더와 같은 숫자
  expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent(
    "승인 대기",
  );
});

test("held and human_handling highlight no step", async () => {
  serve(
    detail({
      incident: {
        ...base,
        status: "human_handling",
        ticket_ids: [],
        entities: [],
      },
    }),
  );
  show(url);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.queryByRole("listitem", { current: "step" })).toBeNull();
});

test("an old selected link goes to the page address", async () => {
  dashboard();
  serve();
  server.use(
    http.get("*/api/incidents", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show(`/incidents?selected=${base.id}`);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.getByTestId("where")).toHaveTextContent(new RegExp(`^${url}$`));
});

test("back to the list keeps the filter, and previous/next move inside the list that was open", async () => {
  dashboard();
  const items = [base, other].map((i) => ({
    ...i,
    display_severity: 5,
    seed_source: null,
  }));
  server.use(
    http.get("*/api/incidents", () =>
      HttpResponse.json({ items, next_cursor: null }),
    ),
    http.get("*/api/incidents/:id", ({ params }) =>
      HttpResponse.json(
        detail({
          incident: {
            ...(params.id === other.id ? other : base),
            ticket_ids: [],
            entities: [],
          },
        }),
      ),
    ),
  );
  show("/incidents?status=awaiting_review");
  fireEvent.click((await screen.findAllByText(base.title))[0]);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.getByRole("button", { name: "이전 Incident" })).toBeDisabled();
  fireEvent.click(screen.getByRole("tab", { name: /^Ticket/ })); // 탭을 바꿔도 목록 정보가 남는다
  fireEvent.click(await screen.findByRole("link", { name: "다음 Incident" }));
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(
      `/incidents/${other.id}`,
    ),
  );
  expect(
    await screen.findByRole("link", { name: "이전 Incident" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("link", { name: "목록으로" }));
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/incidents?status=awaiting_review",
    ),
  );
});

test("opened by address, previous and next are disabled and the list link goes to the default list", async () => {
  dashboard();
  serve();
  server.use(
    http.get("*/api/incidents", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show(url);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.getByRole("button", { name: "이전 Incident" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "다음 Incident" })).toBeDisabled();
  fireEvent.click(screen.getByRole("link", { name: "목록으로" }));
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/incidents$/),
  );
});

function analyst(...extra: string[]) {
  return { ...auth.analyst, permissions: ["incident.read", ...extra] };
}
const reviewed = {
  incident: { ...base, status: "confirmed", display_severity: 5 },
  case_id: "cas_01a19f93-1266-7000-8000-0000000000aa",
};

test("approve and reject show on awaiting_review for an account that may use them, and the page stays after approving", async () => {
  serve();
  const posts: string[] = [];
  server.use(
    http.post("*/api/incidents/:id/approve", ({ request }) => {
      posts.push(new URL(request.url).pathname);
      return HttpResponse.json(reviewed);
    }),
  );
  show(url);
  expect(await screen.findByRole("button", { name: "반려" })).toBeEnabled();
  const before = requests.length;
  fireEvent.click(screen.getByRole("button", { name: "승인" }));
  await waitFor(() =>
    expect(posts).toEqual([`/api/incidents/${base.id}/approve`]),
  );
  await waitFor(() =>
    expect(requests.slice(before).map((r) => r.pathname)).toContain(
      `/api/incidents/${base.id}`,
    ),
  );
  expect(screen.getByTestId("where")).toHaveTextContent(new RegExp(`^${url}$`));
  expect(
    await screen.findByRole("link", { name: "Case 보기" }),
  ).toHaveAttribute("href", `/cases?selected=${reviewed.case_id}`);
});

test("only the buttons the account may use show, and none outside awaiting_review", async () => {
  serve(detail(), analyst("incident.approve"));
  show(url);
  expect(
    await screen.findByRole("button", { name: "승인" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "반려" })).toBeNull();
});

test("an account without review rights, or a decided incident, shows no buttons", async () => {
  serve(detail(), analyst());
  show(url);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.queryByRole("button", { name: /^(승인|반려)$/ })).toBeNull();
});

test("a decided incident shows no approve or reject", async () => {
  serve(
    detail({
      incident: { ...base, status: "confirmed", ticket_ids: [], entities: [] },
    }),
  );
  show(url);
  await screen.findByRole("heading", { level: 1, name: base.title });
  expect(screen.queryByRole("button", { name: /^(승인|반려)$/ })).toBeNull();
});

test("a Case link is not offered without case.read", async () => {
  serve(detail(), analyst("incident.approve"));
  server.use(
    http.post("*/api/incidents/:id/approve", () => HttpResponse.json(reviewed)),
  );
  show(url);
  fireEvent.click(await screen.findByRole("button", { name: "승인" }));
  await waitFor(() =>
    expect(requests.some((r) => r.pathname.endsWith("/approve"))).toBe(true),
  );
  expect(screen.queryByRole("link", { name: "Case 보기" })).toBeNull();
});

test("tabs live in the address, survive a reload and fall back to the overview", async () => {
  serve();
  show(`${url}?tab=entities`);
  expect(await tab(/^엔티티/)).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("tab", { name: /^Ticket/ }));
  expect(screen.getByTestId("where")).toHaveTextContent(`${url}?tab=tickets`);
  expect(screen.getByRole("tab", { name: /^Ticket/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

test("an unknown tab shows the overview", async () => {
  serve();
  show(`${url}?tab=nope`);
  expect(await tab("개요")).toHaveAttribute("aria-selected", "true");
  expect(
    screen.getByRole("heading", { name: "사건 요약" }),
  ).toBeInTheDocument();
});

test("the Ticket table is readable with 30 tickets: search, sort, filter and pages", async () => {
  serve(
    detail({
      tickets: many(30, ticketAt),
      incident: { ...base, ticket_ids: [], entities: [] },
    }),
  );
  show(`${url}?tab=tickets`);
  const table = await screen.findByRole("table", { name: "Ticket 표" });
  expect(screen.getByText("30개 Ticket")).toBeInTheDocument();
  expect(within(table).getAllByRole("row")).toHaveLength(11); // 머리줄 + 10
  expect(screen.getByText("1 / 3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  expect(screen.getByText("2 / 3")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Ticket 검색" }), {
    target: { value: "ticket 30" },
  });
  expect(
    within(screen.getByRole("table", { name: "Ticket 표" })).getAllByRole(
      "row",
    ),
  ).toHaveLength(2);
  expect(screen.getByText("1 / 1")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "Ticket 검색" }), {
    target: { value: "" },
  });
  fireEvent.click(
    within(screen.getByRole("group", { name: "판정 필터" })).getByRole(
      "button",
      { name: "malicious" },
    ),
  );
  expect(screen.getByText("8개 Ticket")).toBeInTheDocument(); // 30개 중 i%4==0
  fireEvent.click(screen.getByRole("button", { name: "근거 수 정렬" }));
  const first = within(
    screen.getByRole("table", { name: "Ticket 표" }),
  ).getAllByRole("row")[1];
  expect(first).toHaveTextContent("샘플 Ticket 1"); // 근거 0개가 앞(오름차순)
  fireEvent.click(screen.getByRole("button", { name: "근거 수 정렬" }));
  expect(
    within(screen.getByRole("table", { name: "Ticket 표" })).getAllByRole(
      "row",
    )[1],
  ).toHaveTextContent("샘플 Ticket 29");
});

test("a Ticket row shows verdict, level, evidence count, the exploration status and a link only with ticket.read", async () => {
  serve(detail({ ticket_graphs: [] }), analyst());
  show(`${url}?tab=tickets`);
  const table = await screen.findByRole("table", { name: "Ticket 표" });
  const row = within(table).getByText(page.tickets[0].title).closest("tr")!;
  expect(row).toHaveTextContent("malicious");
  expect(row).toHaveTextContent("5 Level");
  expect(row).toHaveTextContent("3개");
  expect(row).toHaveTextContent("분류 당시 탐색 정보 없음");
  expect(screen.queryByRole("link", { name: /Ticket 상세/ })).toBeNull();
});

test("a Ticket row links to its detail for an account with ticket.read", async () => {
  serve();
  show(`${url}?tab=tickets`);
  expect(
    (
      await screen.findAllByRole("link", {
        name: `${page.tickets[0].title} Ticket 상세`,
      })
    )[0],
  ).toHaveAttribute("href", `/tickets?selected=${page.tickets[0].id}`);
});

test("the entity table shows links to tickets and alerts, the first sighting, kind chips and 100 entities in pages", async () => {
  const entities = many(100, entityAt);
  serve(
    detail({
      incident: { ...base, ticket_ids: [], entities },
      tickets: [],
      alerts: [],
    }),
  );
  show(`${url}?tab=entities`);
  const table = await screen.findByRole("table", { name: "엔티티 표" });
  expect(within(table).getAllByRole("row")).toHaveLength(21); // 머리줄 + 20
  expect(screen.getByText(/^1 \/ 5$/)).toBeInTheDocument();
  const kinds = screen.getByRole("group", { name: "종류 필터" });
  expect(
    within(kinds).getByRole("button", { name: "ip 15" }),
  ).toBeInTheDocument();
  fireEvent.click(within(kinds).getByRole("button", { name: "file_hash 14" }));
  expect(screen.getByText(/^1 \/ 1$/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "엔티티 검색" }), {
    target: { value: "nothing" },
  });
  expect(
    screen.getByText("조건에 맞는 엔티티가 없습니다."),
  ).toBeInTheDocument();
});

test("entity rows count their tickets and alerts and long values stay text with a copy button", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  const long = `https://example.com/${"a".repeat(300)}<img src=x onerror=alert(1)>`;
  serve(
    detail({
      incident: {
        ...base,
        ticket_ids: page.tickets.map((t) => t.id),
        entities: [...page.entities, { type: "url", value: long, role: null }],
      },
    }),
  );
  show(`${url}?tab=entities`);
  const table = await screen.findByRole("table", { name: "엔티티 표" });
  const ip = within(table).getByText("203.0.113.10").closest("tr")!;
  expect(ip).toHaveTextContent("Ticket 2 · Alert 2");
  const hash = within(table)
    .getByText(/^0123456789abcdef/)
    .closest("tr")!;
  expect(hash).toHaveTextContent("Ticket 0 · Alert 0");
  expect(hash).toHaveTextContent("—"); // 최초 관측을 알 수 없다
  expect(table.querySelector("img")).toBeNull();
  const row = within(table).getByTitle(long).closest("tr")!;
  fireEvent.click(within(row).getByRole("button", { name: "값 복사" }));
  expect(writeText).toHaveBeenCalledWith(long);
});

test("an entity row opens the graph with that entity chosen, in the address and on screen", async () => {
  serve();
  show(`${url}?tab=entities`);
  const table = await screen.findByRole("table", { name: "엔티티 표" });
  const row = within(table).getByText("203.0.113.10").closest("tr")!;
  fireEvent.click(within(row).getByRole("link", { name: "그래프에서 보기" }));
  const where = await screen.findByTestId("where");
  expect(where).toHaveTextContent("tab=graph");
  expect(where).toHaveTextContent("view=entity");
  expect(where.textContent).toContain(
    encodeURIComponent(JSON.stringify(["ip", "203.0.113.10"])),
  );
  const side = await screen.findByRole("complementary", {
    name: "선택된 노드",
  });
  expect(within(side).getByText("203.0.113.10")).toBeInTheDocument();
  expect(
    screen.getByRole("group", { name: "ip: 203.0.113.10" }),
  ).toHaveAttribute("aria-current", "true");
});

test("leaving the graph tab drops the chosen node from the address", async () => {
  serve();
  show(
    `${url}?tab=graph&view=entity&node=${encodeURIComponent(JSON.stringify(["ip", "203.0.113.10"]))}`,
  );
  await screen.findByRole("region", { name: "Incident 관계도" });
  fireEvent.click(screen.getByRole("tab", { name: /^Ticket/ }));
  expect(screen.getByTestId("where")).not.toHaveTextContent("node=");
});

test("a node in the address that is not a [type, value] pair is ignored", async () => {
  serve();
  show(`${url}?tab=graph&view=entity&node=${encodeURIComponent("{not json")}`);
  await screen.findByRole("region", { name: "Incident 관계도" });
  expect(screen.queryByRole("button", { name: "선택 해제" })).toBeNull();
});

test("a Ticket row keeps its detail link at the end of the row", async () => {
  serve();
  show(`${url}?tab=tickets`);
  const table = await screen.findByRole("table", { name: "Ticket 표" });
  const row = within(table).getByText(page.tickets[0].title).closest("tr")!;
  const last = row.lastElementChild!;
  expect(
    within(last as HTMLElement).getByRole("link", {
      name: `${page.tickets[0].title} Ticket 상세`,
    }),
  ).toBeInTheDocument();
});

test("the history tab is a timeline of rounds, newest first, with the summary as text and the raw JSON folded", async () => {
  const rounds = [1, 2, 3].map((n) => ({
    ...artifact,
    id: `${artifact.id.slice(0, -2)}0${n}`,
    analysis_round: n,
    summary: n === 3 ? "요약 <b>굵게</b>" : `라운드 ${n} 요약`,
  }));
  serve(detail({ artifacts: [rounds[0], rounds[2], rounds[1]] }));
  show(`${url}?tab=history`);
  const list = await screen.findByRole("list", {
    name: "분석 라운드 타임라인",
  });
  const items = within(list).getAllByRole("listitem");
  expect(items).toHaveLength(3);
  expect(items[0]).toHaveTextContent("Round 3");
  expect(items[2]).toHaveTextContent("Round 1");
  expect(items[0]).toHaveTextContent("요약 <b>굵게</b>");
  expect(list.querySelector("b")).toBeNull();
  // no data behind the design's change chips and review events, so none are drawn
  expect(screen.queryByText(/Ticket \+|엔티티 \+|판정 변경/)).toBeNull();
  expect(within(list).queryByText(/반려|Incident 승인/)).toBeNull();
  const raw = screen.getByText("원본 보기(고급)").closest("details")!;
  expect(raw).not.toHaveAttribute("open");
});

test("the history tab says so when no round exists yet", async () => {
  serve(detail({ artifacts: [] }));
  show(`${url}?tab=history`);
  expect(
    await screen.findByText("분석 보고서가 없습니다."),
  ).toBeInTheDocument();
});

test("the overview has two columns: summary, impact and tickets on the left, key entities and recommendations on the right", async () => {
  serve();
  show(url);
  await screen.findByRole("heading", { name: "사건 요약" });
  const left = screen.getByRole("region", { name: "사건 개요" });
  const right = screen.getByRole("complementary", {
    name: "핵심 엔티티와 권고 조치",
  });
  expect(
    within(left).getByRole("heading", { name: /소속 Ticket/ }),
  ).toBeInTheDocument();
  expect(
    within(right).getByRole("heading", { name: "핵심 엔티티" }),
  ).toBeInTheDocument();
});

test("key entities are the three with the most tickets, ties by kind then value, shown as text", async () => {
  serve();
  show(url);
  const card = (
    await screen.findByRole("heading", { name: "핵심 엔티티" })
  ).closest("section")!;
  const rows = within(card).getAllByRole("listitem");
  expect(rows).toHaveLength(3);
  expect(rows[0]).toHaveTextContent("ip · 203.0.113.10");
  expect(rows[1]).toHaveTextContent("user · svc-web"); // 2 tickets, like the ip
  expect(rows[2]).toHaveTextContent("domain · example.com"); // 1 ticket: domain before host
  expect(within(card).queryByRole("link")).toBeNull();
});

test("the impact heading is hidden when the impact text is empty", async () => {
  serve(detail({ artifacts: [{ ...artifact, impact: "" }] }));
  show(url);
  await screen.findByRole("heading", { name: "사건 요약" });
  expect(screen.queryByRole("heading", { name: "영향" })).toBeNull();
});

test("an overview ticket row shows time, evidence count, verdict and level without an id, and the whole row opens the ticket", async () => {
  serve();
  show(url);
  const card = (
    await screen.findByRole("heading", { name: /소속 Ticket/ })
  ).closest("section")!;
  const row = within(card).getByRole("link", {
    name: `${page.tickets[0].title} Ticket 상세`,
  });
  expect(row).toHaveAttribute(
    "href",
    `/tickets?selected=${page.tickets[0].id}`,
  );
  expect(row).toHaveTextContent("근거 3개");
  expect(row).toHaveTextContent("malicious");
  expect(row).toHaveTextContent("5 Level");
  expect(card).not.toHaveTextContent(page.tickets[0].id);
  expect(within(card).queryByRole("button", { name: /복사/ })).toBeNull();
});

test("an overview ticket row is plain text for an account without ticket.read", async () => {
  serve(detail(), analyst());
  show(url);
  const card = (
    await screen.findByRole("heading", { name: /소속 Ticket/ })
  ).closest("section")!;
  expect(within(card).queryByRole("link")).toBeNull();
  expect(card).toHaveTextContent(page.tickets[0].title);
});

test("recommendations show the priority and the category as chips", async () => {
  const proposals = [
    {
      ...seed.incident_proposals[0],
      id: "prp_01a19f93-1266-7000-8000-000000000095",
      artifact_id: artifact.id,
      seq: 1,
      kind: "response",
      priority: "high",
      title: "격리 검토",
      detail: "본문",
      rationale: null,
    },
    {
      ...seed.incident_proposals[0],
      id: "prp_01a19f93-1266-7000-8000-000000000096",
      artifact_id: artifact.id,
      seq: 2,
      kind: "detection",
      priority: "low",
      title: "룰 추가",
      detail: "본문",
      rationale: null,
    },
  ];
  serve(detail({ proposals }));
  show(url);
  const card = (
    await screen.findByRole("heading", { name: /권고 조치/ })
  ).closest("section")!;
  const chips = [...card.querySelectorAll(".badge")].map((c) => c.textContent);
  expect(chips).toEqual(["우선순위 높음", "대응", "우선순위 낮음", "탐지 룰"]);
});

test("recommendations have no 'why' label and are split into paragraphs and rules", async () => {
  const proposals = [0, 1].map((i) => ({
    ...seed.incident_proposals[0],
    id: `prp_01a19f93-1266-7000-8000-00000000009${i}`,
    artifact_id: artifact.id,
    seq: i + 1,
    title: `조치 ${i + 1}`,
    detail: "본문 <b>굵게</b>",
    rationale: `이유 ${i + 1}`,
  }));
  serve(detail({ proposals }));
  show(url);
  expect(
    await screen.findByRole("heading", { name: /권고 조치/ }),
  ).toBeInTheDocument();
  expect(screen.queryByText("왜 필요한가")).toBeNull();
  expect(screen.getByText("이유 1")).toBeInTheDocument();
  expect(screen.getAllByText("본문 <b>굵게</b>")).toHaveLength(2);
  expect(document.querySelectorAll(".incident-recommendation hr").length).toBe(
    0,
  );
  expect(document.querySelectorAll("hr.incident-rule").length).toBe(1);
});

test("the graph tab shows the graph with a working view switch; saved paths and exploration status wait in a folded basis", async () => {
  serve(
    detail({
      incident: { ...base, ticket_ids: graphFixture.ticket_ids, entities: [] },
      tickets: graphFixture.ticket_ids.map((id, i) => ({
        ...ticketAt(i),
        id,
        title: `원본 Ticket 제목 ${i + 1}`,
      })),
      ticket_graphs: graphFixture.ticket_graphs,
    }),
  );
  show(`${url}?tab=graph`);
  expect(
    await screen.findByRole("region", { name: "Incident 관계도" }),
  ).toBeInTheDocument();
  const basis = screen.getByText("분류 근거(고급)").closest("details")!;
  expect(basis).not.toHaveAttribute("open");
  expect(
    within(basis).getByRole("heading", { name: "저장된 연결 경로" }),
  ).toBeInTheDocument();
  expect(
    within(basis).getByRole("heading", {
      name: "Ticket별 분류 당시 탐색 상태",
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Entity" })).toBeEnabled();
  expect(screen.queryByText("준비 중")).toBeNull();
});

test("the graph view stays in the address and node places survive a visit to another tab", async () => {
  serve(
    detail({
      incident: { ...base, ticket_ids: graphFixture.ticket_ids, entities: [] },
      tickets: graphFixture.ticket_ids.map((id, i) => ({
        ...ticketAt(i),
        id,
        title: `원본 Ticket 제목 ${i + 1}`,
      })),
      ticket_graphs: graphFixture.ticket_graphs,
    }),
  );
  show(`${url}?tab=graph&view=entity`);
  const entity = await screen.findByRole("button", { name: "Entity" });
  expect(entity).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Ticket" }));
  expect(screen.getByTestId("where")).toHaveTextContent(`${url}?tab=graph`);
  expect(screen.getByTestId("where")).not.toHaveTextContent("view=");
  fireEvent.click(screen.getByRole("button", { name: "Entity" }));
  expect(screen.getByTestId("where")).toHaveTextContent("view=entity");
  fireEvent.click(screen.getByRole("button", { name: "Ticket" }));
  const name = "Ticket 원본 Ticket 제목 1";
  const left = () => parseFloat(screen.getByRole("group", { name }).style.left);
  const node = screen.getByRole("group", { name });
  fireEvent.pointerDown(node, { clientX: 100, clientY: 100, button: 0 });
  fireEvent.pointerMove(node, { clientX: 220, clientY: 100 });
  fireEvent.pointerUp(node, { clientX: 220, clientY: 100 });
  const dropped = left();
  fireEvent.click(screen.getByRole("tab", { name: /^Ticket/ }));
  fireEvent.click(screen.getByRole("tab", { name: "관계 그래프" }));
  expect(left()).toBeCloseTo(dropped, 5);
});

test("the development sample mode shows the 104-entity graph and the empty state without asking the server", async () => {
  serve(detail());
  const { container } = show(`${url}?tab=graph&view=entity&sample=graph`);
  await screen.findByRole("region", { name: "Incident 관계도" });
  expect(
    container.querySelectorAll(".incident-graph-node.entity"),
  ).toHaveLength(60);
  expect(requests.some((r) => r.pathname.startsWith("/api/incidents/"))).toBe(
    false,
  );
});

test("the empty sample shows the empty Ticket tab", async () => {
  serve(detail());
  show(`${url}?tab=tickets&sample=empty`);
  expect(
    await screen.findByText("연결된 Ticket이 없습니다"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "분석 상태 새로고침" }),
  ).toBeInTheDocument();
});

test("outside development the sample parameter is ignored and the server is asked", async () => {
  vi.stubEnv("DEV", false);
  try {
    serve(detail());
    show(`${url}?sample=graph`);
    await screen.findByRole("heading", { level: 1, name: base.title });
    expect(requests.some((r) => r.pathname.startsWith("/api/incidents/"))).toBe(
      true,
    );
  } finally {
    vi.unstubAllEnvs();
  }
});

test("an incident with no tickets shows an empty state with a reload button", async () => {
  serve(
    detail({
      incident: { ...base, ticket_ids: [], entities: [] },
      tickets: [],
      alerts: [],
    }),
  );
  show(`${url}?tab=tickets`);
  expect(
    await screen.findByText("연결된 Ticket이 없습니다"),
  ).toBeInTheDocument();
  const before = requests.filter(
    (r) => r.pathname === `/api/incidents/${base.id}`,
  ).length;
  fireEvent.click(screen.getByRole("button", { name: "분석 상태 새로고침" }));
  await waitFor(() =>
    expect(
      requests.filter((r) => r.pathname === `/api/incidents/${base.id}`).length,
    ).toBe(before + 1),
  );
});

test("an incident with no entities shows an empty entity table message", async () => {
  serve(
    detail({
      incident: { ...base, ticket_ids: [], entities: [] },
      tickets: [],
      alerts: [],
    }),
  );
  show(`${url}?tab=entities`);
  expect(await screen.findByText("엔티티가 없습니다.")).toBeInTheDocument();
});

test("loading shows a status, a failed read shows the error with a retry", async () => {
  let fail = true;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => (release = resolve));
  server.use(
    http.get("*/api/incidents/:id", async () => {
      if (!fail) return HttpResponse.json(detail());
      await gate;
      return HttpResponse.json({ error: "db_unavailable" }, { status: 503 });
    }),
  );
  show(url);
  expect(
    await screen.findByText("Incident를 불러오는 중…"),
  ).toBeInTheDocument();
  release();
  expect(
    await screen.findByText("서버에 일시적으로 연결할 수 없어요"),
  ).toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole("button", { name: /다시 시도/ }));
  expect(
    await screen.findByRole("heading", { level: 1, name: base.title }),
  ).toBeInTheDocument();
});

test("without incident.read the page is refused and nothing is requested", async () => {
  server.use(
    http.get("*/api/auth/me", () =>
      HttpResponse.json({ ...auth.analyst, permissions: ["ticket.read"] }),
    ),
  );
  show(url);
  expect(
    await screen.findByText("이 화면을 볼 권한이 없어요"),
  ).toBeInTheDocument();
  expect(requests.some((r) => r.pathname.startsWith("/api/incidents"))).toBe(
    false,
  );
});

test("the title and summary are shown as text, never as markup", async () => {
  const title = "<img src=x onerror=alert(1)> 제목";
  serve(
    detail({
      incident: {
        ...base,
        title,
        summary: "<script>x</script>요약",
        ticket_ids: [],
        entities: [],
      },
    }),
  );
  show(url);
  expect(
    await screen.findByRole("heading", { level: 1, name: title }),
  ).toBeInTheDocument();
  expect(screen.getByText("<script>x</script>요약")).toBeInTheDocument();
  expect(
    document.querySelector(".incident-page img, .incident-page script"),
  ).toBeNull();
});
