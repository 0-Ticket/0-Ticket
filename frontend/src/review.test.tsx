import { expect, test } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import seed from "../../tests/fixtures/api/ui_seed.json";
import { auth, dashboard, requests, server, show } from "./test-utils";

const incident = seed.incidents[1]; // awaiting_review
const artifact = seed.incident_artifacts.find(
  (a) => a.incident_id === incident.id,
)!;
const tickets = [5, 6].map((i) => ({
  id: seed.tickets[i].id,
  title: seed.tickets[i].title,
  decision: null,
  severity: 4,
  created_at: seed.tickets[i].created_at,
  evidence_count: 0,
  alert_ids: [],
  entities: [],
}));

function detail(overrides: Record<string, unknown> = {}) {
  return {
    incident,
    tickets,
    alerts: [],
    artifacts: [artifact],
    proposals: [],
    ticket_graphs: [],
    seed_source: "dev-seed-ui",
    ...overrides,
  };
}
function serve(body: object, me: object = auth.admin) {
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json(me)),
    http.get("*/api/incidents", () =>
      HttpResponse.json({
        items: [{ ...incident, display_severity: 5, seed_source: null }],
        next_cursor: null,
      }),
    ),
    http.get("*/api/incidents/:id", () => HttpResponse.json(body)),
  );
}
// The incident opens as a page (#379); the tests look inside its content.
async function open(tab = "") {
  show(`/incidents/${incident.id}${tab}`);
  await screen.findByRole("heading", { level: 1, name: incident.title });
  return document.querySelector<HTMLElement>(".incident-page")!;
}
function analystWith(...extra: string[]) {
  return {
    ...auth.analyst,
    permissions: [...auth.analyst.permissions, ...extra],
  };
}
const reviewed = {
  incident: { ...incident, status: "confirmed", display_severity: 5 },
  case_id: "cas_01a19f93-1266-7000-8000-0000000000aa",
};

test("an admin sees approve and reject on an awaiting_review incident, with no 'not provided' note", async () => {
  dashboard();
  serve(detail());
  const dialog = await open();
  expect(
    await within(dialog).findByRole("button", { name: "승인" }),
  ).toBeEnabled();
  expect(within(dialog).getByRole("button", { name: "반려" })).toBeEnabled();
  expect(dialog).not.toHaveTextContent("아직 제공하지 않습니다");
});

test("approving posts once, reloads the detail, and the lists and dashboard are read again when the list is shown", async () => {
  dashboard();
  serve(detail());
  const posts: string[] = [];
  server.use(
    http.post("*/api/incidents/:id/approve", ({ request }) => {
      posts.push(new URL(request.url).pathname);
      return HttpResponse.json(reviewed);
    }),
  );
  show("/incidents"); // the list is read first, so there is something cached to be marked stale
  fireEvent.click(await screen.findByText(incident.title));
  const page = (await screen.findByRole("heading", { level: 1 })).closest(
    ".incident-page",
  ) as HTMLElement;
  const before = requests.length;
  fireEvent.click(await within(page).findByRole("button", { name: "승인" }));
  await waitFor(() =>
    expect(
      requests
        .slice(before)
        .some((r) => r.pathname === `/api/incidents/${incident.id}`),
    ).toBe(true),
  );
  expect(posts).toEqual([`/api/incidents/${incident.id}/approve`]);
  expect(screen.getByTestId("where")).toHaveTextContent(
    `/incidents/${incident.id}`,
  );
  const back = requests.length;
  fireEvent.click(within(page).getByRole("link", { name: "목록으로" }));
  await waitFor(() => {
    const after = requests.slice(back).map((r) => r.pathname);
    expect(after).toContain("/api/incidents");
    expect(after).toContain("/api/dashboard");
  });
});

function serveReject() {
  const sent: { path: string; body: string }[] = [];
  server.use(
    http.post("*/api/incidents/:id/reject", async ({ request }) => {
      sent.push({
        path: new URL(request.url).pathname,
        body: await request.text(),
      });
      return HttpResponse.json({
        incident: { ...incident, status: "analyzing", display_severity: 5 },
        case_id: null,
      });
    }),
  );
  return sent;
}
async function openRejectDialog() {
  const page = await open();
  fireEvent.click(await within(page).findByRole("button", { name: "반려" }));
  return screen.getByRole("dialog", { name: "Incident 반려" });
}

test("rejecting asks in a dialog with an optional reason box and sends nothing until confirmed", async () => {
  dashboard();
  serve(detail());
  const sent = serveReject();
  const dialog = await openRejectDialog();
  const box = within(dialog).getByRole("textbox", { name: /반려 사유/ });
  expect(box).toHaveAttribute("maxlength", "500");
  expect(box).not.toBeRequired();
  expect(sent).toEqual([]);
});

test("confirming with the reason box empty still rejects, with no body", async () => {
  dashboard();
  serve(detail());
  const sent = serveReject();
  const dialog = await openRejectDialog();
  fireEvent.click(within(dialog).getByRole("button", { name: "반려하기" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toEqual({
    path: `/api/incidents/${incident.id}/reject`,
    body: "",
  });
});

test("a reason with only spaces is not sent", async () => {
  dashboard();
  serve(detail());
  const sent = serveReject();
  const dialog = await openRejectDialog();
  fireEvent.change(within(dialog).getByRole("textbox"), {
    target: { value: "  \n " },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "반려하기" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].body).toBe("");
});

test("confirming with a reason sends it as the reason field, text as typed", async () => {
  dashboard();
  serve(detail());
  const sent = serveReject();
  const dialog = await openRejectDialog();
  fireEvent.change(within(dialog).getByRole("textbox"), {
    target: { value: "근거가 부족해요 <b>x</b>" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "반려하기" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(JSON.parse(sent[0].body)).toEqual({
    reason: "근거가 부족해요 <b>x</b>",
  });
});

test("cancelling closes the dialog without a request and forgets the typed reason", async () => {
  dashboard();
  serve(detail());
  const sent = serveReject();
  const dialog = await openRejectDialog();
  fireEvent.change(within(dialog).getByRole("textbox"), {
    target: { value: "버릴 사유" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "취소" }));
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Incident 반려" })).toBeNull(),
  );
  expect(sent).toEqual([]);
  const again = await openRejectDialog();
  expect(within(again).getByRole("textbox")).toHaveValue("");
});

test("a refused rejection (409) keeps the message on the page and reloads", async () => {
  dashboard();
  serve(detail());
  server.use(
    http.post("*/api/incidents/:id/reject", () =>
      HttpResponse.json(
        { error: "incident_not_awaiting_review", status: "analyzing" },
        { status: 409 },
      ),
    ),
  );
  const dialog = await openRejectDialog();
  fireEvent.click(within(dialog).getByRole("button", { name: "반려하기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("이미 처리된");
});

test("a request refused with 409 says the incident was already handled and reloads", async () => {
  dashboard();
  serve(detail());
  server.use(
    http.post("*/api/incidents/:id/approve", () =>
      HttpResponse.json(
        { error: "incident_not_awaiting_review", status: "confirmed" },
        { status: 409 },
      ),
    ),
  );
  const dialog = await open();
  const before = requests.length;
  fireEvent.click(await within(dialog).findByRole("button", { name: "승인" }));
  expect(
    await within(dialog).findByText(/이미 처리된 Incident예요/),
  ).toBeInTheDocument();
  expect(dialog).toHaveTextContent("승인 / 확인됨"); // 지금 상태를 이름으로 보여 준다
  await waitFor(() =>
    expect(
      requests
        .slice(before)
        .filter((r) => r.pathname === `/api/incidents/${incident.id}`).length,
    ).toBeGreaterThan(0),
  );
});

test("only the buttons the account may use are shown", async () => {
  dashboard();
  serve(detail(), analystWith("incident.read", "incident.reject"));
  const dialog = await open();
  expect(
    await within(dialog).findByRole("button", { name: "반려" }),
  ).toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: "승인" })).toBeNull();
});

test("an account without the approval permissions sees no buttons and no note", async () => {
  dashboard();
  serve(detail(), auth.analyst);
  const dialog = await open();
  await within(dialog).findByText("사건 요약");
  expect(within(dialog).queryByRole("button", { name: "승인" })).toBeNull();
  expect(within(dialog).queryByRole("button", { name: "반려" })).toBeNull();
  expect(dialog).not.toHaveTextContent("아직 제공하지 않습니다");
});

test.each(["analyzing", "confirmed", "human_handling", "dismissed", "held"])(
  "an incident in %s has no approve or reject buttons",
  async (status) => {
    dashboard();
    serve(detail({ incident: { ...incident, status } }));
    const dialog = await open();
    await within(dialog).findByText("사건 요약");
    expect(within(dialog).queryByRole("button", { name: "승인" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "반려" })).toBeNull();
  },
);

test("incident detail shows each ticket by title with a link to its detail", async () => {
  dashboard();
  serve(detail());
  const dialog = await open();
  for (const t of tickets) {
    expect(
      (await within(dialog).findAllByText(t.title)).length,
    ).toBeGreaterThan(0);
    expect(
      within(dialog).getByRole("link", { name: `${t.title} Ticket 상세` }),
    ).toHaveAttribute("href", `/tickets?selected=${t.id}`);
  }
  expect(dialog).toHaveTextContent("소속 Ticket");
  expect(dialog).toHaveTextContent(`${tickets.length}건`);
});

test("only the latest round's recommendations are shown, and empty priority or rationale is fine", async () => {
  dashboard();
  const old = {
    ...artifact,
    id: "art_01a19f93-1266-7000-8000-0000000000e1",
    analysis_round: 1,
  };
  const latest = {
    ...artifact,
    id: "art_01a19f93-1266-7000-8000-0000000000e2",
    analysis_round: 2,
  };
  const proposal = (id: string, art: string, extra = {}) => ({
    id,
    artifact_id: art,
    kind: "response",
    seq: 1,
    priority: null,
    title: "옛 제안",
    detail: "본문",
    rationale: null,
    ...extra,
  });
  serve(
    detail({
      artifacts: [latest, old],
      proposals: [
        proposal("prp_01a19f93-1266-7000-8000-0000000000f1", latest.id, {
          title: "최신 제안 A",
          priority: "high",
          rationale: "이유 A",
        }),
        proposal("prp_01a19f93-1266-7000-8000-0000000000f2", latest.id, {
          title: "최신 제안 B",
          seq: 2,
          kind: "detection",
        }),
        proposal("prp_01a19f93-1266-7000-8000-0000000000f3", old.id),
      ],
    }),
  );
  const dialog = await open();
  expect(await within(dialog).findByText("최신 제안 A")).toBeInTheDocument();
  expect(within(dialog).getByText("최신 제안 B")).toBeInTheDocument();
  expect(within(dialog).queryByText("옛 제안")).toBeNull();
  expect(dialog).toHaveTextContent("우선순위 높음");
  expect(dialog).toHaveTextContent("이유 A");
  expect(dialog).toHaveTextContent("권고 조치");
});

test("an incident with no analysis shows no recommendations section and does not crash", async () => {
  dashboard();
  serve(detail({ artifacts: [], proposals: [] }));
  const dialog = await open();
  expect(await within(dialog).findByText("사건 요약")).toBeInTheDocument();
  expect(dialog).not.toHaveTextContent("권고 조치");
  fireEvent.click(within(dialog).getByRole("tab", { name: /^분석 이력/ }));
  expect(
    await within(dialog).findByText("분석 보고서가 없습니다."),
  ).toBeInTheDocument();
});

test("recommendation text stays text", async () => {
  dashboard();
  const latest = artifact;
  serve(
    detail({
      proposals: [
        {
          id: "prp_01a19f93-1266-7000-8000-0000000000f9",
          artifact_id: latest.id,
          kind: "response",
          seq: 1,
          priority: "low",
          title: "<img src=x onerror=alert(1)>",
          detail: "<script>alert(1)</script>",
          rationale: "<b>x</b>",
        },
      ],
    }),
  );
  const dialog = await open();
  await within(dialog).findByText("<img src=x onerror=alert(1)>");
  expect(dialog.querySelector("img, script, b")).toBeNull();
});

// The screen reads the incident again on a timer; "online" makes the same automatic read at once.
async function refresh() {
  const count = () =>
    requests.filter((r) => r.pathname === `/api/incidents/${incident.id}`)
      .length;
  const before = count();
  window.dispatchEvent(new Event("online"));
  await waitFor(() => expect(count()).toBeGreaterThan(before));
  await new Promise((done) => setTimeout(done, 30)); // let the answer reach the screen
}
async function typedReason() {
  const dialog = await openRejectDialog();
  fireEvent.change(within(dialog).getByRole("textbox"), {
    target: { value: "근거가 부족해요" },
  });
  return dialog;
}
const reject = (dialog: HTMLElement) =>
  within(dialog).getByRole("button", { name: "반려하기" });

test("the reject window and the typed reason stay while the incident leaves review, and rejecting is off", async () => {
  dashboard();
  serve(detail());
  const dialog = await typedReason();
  serve(detail({ incident: { ...incident, status: "analyzing" } }));
  await refresh();
  expect(dialog).toHaveTextContent("현재 상태: 분석 중. 반려할 수 없어요.");
  expect(within(dialog).getByRole("textbox")).toHaveValue("근거가 부족해요");
  expect(reject(dialog)).toBeDisabled();
  // Back to review with the same numbers: the window says it moved, and rejecting works again.
  serve(detail());
  await refresh();
  expect(dialog).toHaveTextContent("분석·검토가 바뀌었어요");
  expect(dialog).not.toHaveTextContent("반려할 수 없어요");
  expect(within(dialog).getByRole("textbox")).toHaveValue("근거가 부족해요");
  expect(reject(dialog)).toBeEnabled();
});

test.each([
  ["a re-analysis finished", { analysis_round: incident.analysis_round + 1 }],
  ["a review was recorded", { review_round: incident.review_round + 1 }],
])(
  "still in review but %s since the window opened: the window says it changed",
  async (_name, changed) => {
    dashboard();
    serve(detail());
    const dialog = await typedReason();
    expect(dialog).not.toHaveTextContent("바뀌었어요");
    serve(detail({ incident: { ...incident, ...changed } }));
    await refresh();
    expect(dialog).toHaveTextContent("분석·검토가 바뀌었어요");
    expect(reject(dialog)).toBeEnabled();
    expect(within(dialog).getByRole("textbox")).toHaveValue("근거가 부족해요");
  },
);

test("a refresh that changes nothing leaves the reject window as it was", async () => {
  dashboard();
  serve(detail());
  const dialog = await typedReason();
  await refresh();
  expect(dialog).not.toHaveTextContent("바뀌었어요");
  expect(dialog).not.toHaveTextContent("반려할 수 없어요");
  expect(reject(dialog)).toBeEnabled();
  expect(within(dialog).getByRole("textbox")).toHaveValue("근거가 부족해요");
});

test("the 409 note survives the reload that shows the incident is no longer in review", async () => {
  dashboard();
  serve(detail());
  server.use(
    http.post("*/api/incidents/:id/approve", () => {
      // The reload that follows sees the result of whoever got there first.
      serve(detail({ incident: { ...incident, status: "confirmed" } }));
      return HttpResponse.json(
        { error: "incident_not_awaiting_review", status: "confirmed" },
        { status: 409 },
      );
    }),
  );
  const page = await open();
  fireEvent.click(await within(page).findByRole("button", { name: "승인" }));
  await waitFor(() =>
    expect(within(page).queryByRole("button", { name: "승인" })).toBeNull(),
  );
  expect(await within(page).findByRole("alert")).toHaveTextContent(
    "이미 처리된 Incident예요(현재 상태: 승인 / 확인됨)",
  );
});
