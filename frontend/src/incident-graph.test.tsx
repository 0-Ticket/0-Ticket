import { expect, test } from "vitest";
import { render, screen, within } from "@testing-library/react";
import seed from "../../tests/fixtures/api/ui_seed.json";
import sample from "../../tests/fixtures/frontend/incident_graph.json";
import type { IncidentDetail } from "./api/generated/IncidentDetail";
import { IncidentGraph } from "./incident-graph";

const incident = {
  ...seed.incidents[1],
  ticket_ids: sample.ticket_ids,
} as unknown as IncidentDetail["incident"];
const graphs = sample.ticket_graphs as IncidentDetail["ticket_graphs"];

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
