import { expect, test } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import seed from "../../tests/fixtures/api/ui_seed.json";
import sample from "../../tests/fixtures/frontend/incident_graph.json";
import type { IncidentDetail } from "./api/generated/IncidentDetail";
import { IncidentGraph } from "./incident-graph";

const incident = {
  ...seed.incidents[1],
  ticket_ids: sample.ticket_ids,
} as unknown as IncidentDetail["incident"];
const graphs = sample.ticket_graphs as IncidentDetail["ticket_graphs"];

test("shows a vector-only membership without inventing a graph path", () => {
  const candidate = {
    ...graphs![0],
    paths: [],
    vector_only: true,
    vector_score: 0.81234,
    representative_ticket_id: sample.ticket_ids[1],
  };
  render(<IncidentGraph incident={incident} ticketGraphs={[candidate]} />);
  expect(
    screen.getByText(
      /유사 Ticket 후보로 연결 \(유사도 0\.812, 그래프 경로 없음\)/,
    ),
  ).toBeInTheDocument();
});

test("shows rejected vector candidates on a new incident", () => {
  render(
    <IncidentGraph
      incident={incident}
      ticketGraphs={[
        { ...graphs![0], paths: [], reason: "no_path", candidate_count: 2 },
      ]}
    />,
  );
  expect(
    screen.getByText(/유사 Ticket 후보 검토 완료 \(그래프 경로 없음\)/),
  ).toBeInTheDocument();
});

test("merges shared entities and edges while keeping membership and historical states distinct", () => {
  const { container } = render(
    <IncidentGraph incident={incident} ticketGraphs={graphs} />,
  );
  const diagram = screen.getByRole("region", { name: "Incident 관계도" });
  expect(diagram).toHaveAttribute("tabindex", "0");
  expect(
    within(diagram).getByRole("group", { name: "host: lab-7" }),
  ).toHaveAttribute("tabindex", "0");
  expect(
    container.querySelector<HTMLElement>(".incident-graph-node.incident")?.style
      .left,
  ).toBe("24px");
  expect(within(diagram).getAllByText("lab-7")).toHaveLength(1);
  expect(within(diagram).queryByText("other.example.com")).toBeNull();
  expect(container.querySelectorAll("line[data-relation='path']")).toHaveLength(
    6,
  );
  expect(
    container.querySelectorAll("line[data-relation='membership']"),
  ).toHaveLength(7);
  expect(screen.getByText(/분류 당시 후보 없음/)).toBeInTheDocument();
  expect(screen.getByText(/후보 한도로 미완료/)).toBeInTheDocument();
  expect(screen.getByText(/과거 경로 기록 없음/)).toBeInTheDocument();
  expect(screen.getByText(/확인 불가/)).toBeInTheDocument();
  expect(screen.getByText(/공용 IP만 일치해 제외/)).toBeInTheDocument();
  const routes = screen.getByRole("list", { name: "저장된 연결 경로" });
  expect(within(routes).getAllByRole("listitem")).toHaveLength(2);
  expect(routes.textContent).toContain(sample.ticket_ids[1]);
  expect(routes.textContent).toContain(sample.ticket_ids[0]);
  expect(routes.textContent).toContain("Hunt");
  expect(routes.textContent).toContain("host: lab-7");
});

test("names the shared entity on every edge that touches it", () => {
  const { container } = render(
    <IncidentGraph incident={incident} ticketGraphs={graphs} />,
  );
  // alert101-entity, entity-alert100, hunt102-entity. 소속선과 Ticket-기록 선에는 붙지 않는다.
  const labels = [
    ...container.querySelectorAll(
      ".incident-graph-lines .incident-graph-edge-label",
    ),
  ];
  expect(labels).toHaveLength(3);
  expect(new Set(labels.map((node) => node.textContent))).toEqual(
    new Set(["host: lab-7"]),
  );
  // 보조기기가 선을 중복해 읽지 않도록 svg는 숨긴 채로 둔다.
  expect(container.querySelector(".incident-graph-lines")).toHaveAttribute(
    "aria-hidden",
    "true",
  );
});

test("shows membership and missing search data without inventing a path", () => {
  const { container } = render(
    <IncidentGraph incident={incident} ticketGraphs={undefined} />,
  );
  expect(
    container.querySelectorAll(".incident-graph-node.ticket"),
  ).toHaveLength(7);
  expect(container.querySelectorAll("line[data-relation='path']")).toHaveLength(
    0,
  );
  expect(screen.getByText(/탐색 기록을 받지 못했습니다/)).toBeInTheDocument();
  expect(
    screen.getByText(/현재 Incident로 이어지는 저장 경로가 없습니다/),
  ).toBeInTheDocument();
});

test("keeps external entity text literal", () => {
  const hostile = structuredClone(sample.ticket_graphs);
  hostile[1].paths[0].nodes[2].value = '<img src=x onerror="alert(1)">';
  const { container } = render(
    <IncidentGraph
      incident={incident}
      ticketGraphs={hostile as IncidentDetail["ticket_graphs"]}
    />,
  );
  expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
  expect(container.querySelector("img, script")).toBeNull();
});

test("lays out many repeated shared-entity paths without overlapping ticket columns", () => {
  const many = Array.from({ length: 22 }, (_, index) => `tkt_sample_${index}`);
  const repeated = many.slice(1).map((ticketId, index) => {
    const path = structuredClone(sample.ticket_graphs[1].paths[0]);
    const alertId = `alt_sample_${index}`;
    path.ticket_id = many[0];
    path.nodes[0].id = ticketId;
    path.nodes[1].id = alertId;
    path.nodes[4].id = many[0];
    path.edges[0].from = ticketId;
    path.edges[0].to = alertId;
    path.edges[1].from = alertId;
    path.edges[3].to = many[0];
    path.edges[4].from = many[0];
    return {
      ticket_id: ticketId,
      coverage: "complete",
      reason: "paths_found",
      paths: [path],
    };
  });
  const { container } = render(
    <IncidentGraph
      incident={{
        ...incident,
        ticket_ids: many as IncidentDetail["incident"]["ticket_ids"],
      }}
      ticketGraphs={repeated as IncidentDetail["ticket_graphs"]}
    />,
  );
  const nodes = [
    ...container.querySelectorAll<HTMLElement>(".incident-graph-node.ticket"),
  ];
  expect(nodes).toHaveLength(22);
  expect(new Set(nodes.map((node) => node.style.left)).size).toBe(22);
  expect(
    container.querySelectorAll(".incident-graph-node.entity"),
  ).toHaveLength(1);
  expect(container.querySelectorAll("line[data-relation='path']")).toHaveLength(
    44,
  );
  expect(
    Number.parseInt(
      container.querySelector<HTMLElement>(".incident-graph-canvas")!.style
        .width,
    ),
  ).toBeGreaterThan(3000);
});

const titles = Object.fromEntries(
  sample.ticket_ids.map((id, i) => [id, `Ticket 제목 ${i}`]),
);
const inspector = () =>
  screen.getByRole("complementary", { name: "선택된 노드" });
const stat = (name: string) =>
  within(inspector()).getByText(name).parentElement!.querySelector("dd")!
    .textContent;

test("the header shows the status and ticket count as chips, and the view toggle offers only the ticket view", () => {
  render(<IncidentGraph incident={incident} ticketGraphs={graphs} />);
  const heading = document.querySelector(".incident-graph-heading")!;
  expect(heading).toHaveTextContent("승인 대기");
  expect(heading).toHaveTextContent(`Ticket ${sample.ticket_ids.length}`);
  const views = screen.getByRole("group", { name: "그래프 보기" });
  expect(within(views).getByRole("button", { name: "Ticket" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(within(views).getByRole("button", { name: "Entity" })).toBeDisabled();
});

test("ticket nodes show the ticket title when titles are given and the id otherwise", () => {
  const { rerender } = render(
    <IncidentGraph incident={incident} ticketGraphs={graphs} titles={titles} />,
  );
  const diagram = screen.getByRole("region", { name: "Incident 관계도" });
  expect(within(diagram).getByText("Ticket 제목 0")).toBeInTheDocument();
  rerender(<IncidentGraph incident={incident} ticketGraphs={graphs} />);
  expect(within(diagram).queryByText("Ticket 제목 0")).toBeNull();
  expect(within(diagram).getByText(sample.ticket_ids[0])).toBeInTheDocument();
});

test("the incident is selected first and the inspector counts its tickets", () => {
  render(<IncidentGraph incident={incident} ticketGraphs={graphs} />);
  expect(inspector()).toHaveTextContent("선택된 노드 · INCIDENT");
  expect(stat("연결 Ticket")).toBe(String(sample.ticket_ids.length));
  expect(stat("자산 중요도")).toBe("—");
});

test("clicking or pressing Enter on a node selects it and fills the inspector", () => {
  const { container } = render(
    <IncidentGraph incident={incident} ticketGraphs={graphs} titles={titles} />,
  );
  const node = (name: string) =>
    within(screen.getByRole("region", { name: "Incident 관계도" })).getByRole(
      "group",
      { name },
    );
  const ticket = node(`Ticket ${sample.ticket_ids[1]}`);
  fireEvent.click(ticket);
  expect(inspector()).toHaveTextContent("선택된 노드 · TICKET");
  expect(inspector()).toHaveTextContent("Ticket 제목 1");
  expect(Number(stat("관련 Alert"))).toBeGreaterThan(0);
  expect(ticket).toHaveAttribute("aria-current", "true");
  fireEvent.keyDown(node("host: lab-7"), { key: "Enter" });
  expect(inspector()).toHaveTextContent("선택된 노드 · ENTITY");
  expect(inspector()).toHaveTextContent("lab-7");
  expect(
    container.querySelectorAll(".incident-graph-node.selected"),
  ).toHaveLength(1);
});

test("hovering a node dims what is not connected to it and leaving restores", () => {
  const { container } = render(
    <IncidentGraph incident={incident} ticketGraphs={graphs} />,
  );
  const dimmed = () =>
    container.querySelectorAll(".incident-graph-node.dim").length;
  expect(dimmed()).toBe(0);
  const entity = screen.getByRole("group", { name: "host: lab-7" });
  fireEvent.mouseEnter(entity);
  expect(dimmed()).toBeGreaterThan(0);
  expect(entity).not.toHaveClass("dim");
  expect(
    container.querySelectorAll(".incident-graph-lines g.on").length,
  ).toBeGreaterThan(0);
  fireEvent.mouseLeave(entity);
  expect(dimmed()).toBe(0);
});

test("entity text stays literal in the inspector too", () => {
  const hostile = structuredClone(sample.ticket_graphs);
  // The shared entity is one node, so every path that names it must carry the same value.
  for (const [g, p] of [
    [1, 0],
    [2, 0],
  ])
    hostile[g].paths[p].nodes[2].value = '<img src=x onerror="alert(1)">';
  const { container } = render(
    <IncidentGraph
      incident={incident}
      ticketGraphs={hostile as IncidentDetail["ticket_graphs"]}
    />,
  );
  fireEvent.click(screen.getByRole("group", { name: /onerror/ }));
  expect(inspector()).toHaveTextContent('<img src=x onerror="alert(1)">');
  expect(container.querySelector("img, script")).toBeNull();
});
