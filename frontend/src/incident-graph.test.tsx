import { useState } from "react";
import { expect, test } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import seed from "../../tests/fixtures/api/ui_seed.json";
import sample from "../../tests/fixtures/frontend/incident_graph.json";
import type { IncidentDetail } from "./api/generated/IncidentDetail";
import { IncidentGraph } from "./incident-graph";
import { ClassificationBasis } from "./incident/basis";
import { useGraphMemory } from "./incident/graph-memory";
import { graphDetail } from "./incident/graph-sample";
import type { GraphView } from "./incident/graph-model";

function Harness({
  detail = graphDetail(),
  initial = "ticket",
  start,
}: {
  detail?: IncidentDetail;
  initial?: GraphView;
  start?: string;
}) {
  const [view, setView] = useState<GraphView>(initial);
  const [memory, setMemory] = useGraphMemory(detail.incident.id);
  const [shown, setShown] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setShown((s) => !s)}>
        탭 전환
      </button>
      {shown && (
        <IncidentGraph
          detail={detail}
          view={view}
          onView={setView}
          memory={memory}
          onMemory={setMemory}
          start={start}
        />
      )}
    </>
  );
}

const nodes = (c: HTMLElement, kind: string) =>
  c.querySelectorAll(`.incident-graph-node.${kind}`);
const node = (name: string) => screen.getByRole("group", { name });
const inspector = () =>
  screen.getByRole("complementary", { name: "선택된 노드" });
const scale = (c: HTMLElement) =>
  Number(
    /scale\(([\d.]+)\)/.exec(
      c.querySelector<HTMLElement>(".incident-graph-world")!.style.transform,
    )![1],
  );

test("opens in the ticket view and switches to the entity view", () => {
  const { container } = render(<Harness />);
  const diagram = screen.getByRole("region", { name: "Incident 관계도" });
  expect(diagram).toHaveAttribute("tabindex", "0");
  const ticket = screen.getByRole("button", { name: "Ticket" });
  const entity = screen.getByRole("button", { name: "Entity" });
  expect(ticket).toHaveAttribute("aria-pressed", "true");
  expect(entity).toBeEnabled();
  expect(nodes(container, "ticket")).toHaveLength(14);
  fireEvent.click(entity);
  expect(entity).toHaveAttribute("aria-pressed", "true");
  expect(nodes(container, "ticket")).toHaveLength(0);
  expect(nodes(container, "entity")).toHaveLength(60);
});

test("alerts are folded into their ticket until it is unfolded", () => {
  const { container } = render(<Harness />);
  expect(nodes(container, "alert")).toHaveLength(0);
  fireEvent.click(
    screen.getByRole("button", { name: "Alert 펼치기: 샘플 Ticket 묶음" }),
  );
  expect(nodes(container, "alert")).toHaveLength(2);
  fireEvent.click(
    screen.getByRole("button", { name: "Alert 접기: 샘플 Ticket 묶음" }),
  );
  expect(nodes(container, "alert")).toHaveLength(0);
  // a ticket with no alert has nothing to unfold
  expect(
    screen.queryByRole("button", { name: /Alert 펼치기: 가설/ }),
  ).toBeNull();
});

test("the entity view says it is cut to 60 and explains the arrows", () => {
  render(<Harness initial="entity" />);
  expect(
    screen.getByText(/연결 수 상위 60개만 표시합니다 \(전체 104개 중 60개\)/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "화살표는 Alert에 기록된 출발→목적지 방향이며 공격 순서가 아님",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/위험 경로|공격 경로/)).toBeNull();
});

test("lines carry no description labels and only src to dst lines have an arrowhead", () => {
  const { container } = render(<Harness initial="entity" />);
  const arrows = container.querySelectorAll("line[data-arrow='true']");
  const plain = container.querySelectorAll("line[data-arrow='false']");
  expect(arrows.length).toBeGreaterThan(0);
  expect(plain.length).toBeGreaterThan(0);
  for (const line of arrows) expect(line).toHaveAttribute("marker-end");
  for (const line of plain) expect(line).not.toHaveAttribute("marker-end");
  expect(container.querySelectorAll(".incident-graph-lines text")).toHaveLength(
    0,
  );
  expect(container.querySelector(".incident-graph-lines")).toHaveAttribute(
    "aria-hidden",
    "true",
  );
});

test("the type filter shows that type only and can be switched off again", () => {
  const { container } = render(<Harness initial="entity" />);
  const chips = screen.getByRole("group", { name: "종류 필터" });
  const ip = within(chips).getByRole("button", { name: "ip" });
  fireEvent.click(ip);
  expect(ip).toHaveAttribute("aria-pressed", "true");
  expect(nodes(container, "entity")).toHaveLength(18);
  fireEvent.click(ip);
  expect(nodes(container, "entity")).toHaveLength(60);
});

test("a search brings in a match below the cut and dims what does not match", () => {
  const { container } = render(<Harness initial="entity" />);
  expect(
    screen.queryByRole("group", { name: "process: proc-14.exe" }),
  ).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "노드 검색" }), {
    target: { value: "proc-14" },
  });
  const hit = node("process: proc-14.exe");
  expect(hit).not.toHaveClass("dim");
  expect(container.querySelectorAll(".incident-graph-node.dim").length).toBe(
    60,
  );
});

const faded = (c: HTMLElement) =>
  c.querySelectorAll(".incident-graph-node.faded");
const fadedLines = (c: HTMLElement) =>
  c.querySelectorAll(".incident-graph-lines line.faded");

test("choosing a node fades everything but its direct neighbours and removes nothing", () => {
  const { container } = render(<Harness initial="entity" />);
  const lines = container.querySelectorAll(".incident-graph-lines line").length;
  fireEvent.click(node("ip: 203.0.113.10"));
  const side = inspector();
  expect(within(side).getByText("203.0.113.10")).toBeInTheDocument();
  expect(within(side).getByText("연결 Ticket").nextSibling).toHaveTextContent(
    "4",
  );
  expect(nodes(container, "entity")).toHaveLength(60);
  expect(container.querySelectorAll(".incident-graph-lines line")).toHaveLength(
    lines,
  );
  const fadedNow = faded(container).length;
  expect(fadedNow).toBeGreaterThan(0);
  expect(fadedNow).toBeLessThan(59);
  expect(node("ip: 203.0.113.10")).not.toHaveClass("faded");
  expect(fadedLines(container).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
  expect(faded(container)).toHaveLength(0);
  expect(fadedLines(container)).toHaveLength(0);
});

test("hovering fades the same way in both views, overrides the choice and goes back when the pointer leaves", () => {
  const { container } = render(<Harness />);
  fireEvent.mouseEnter(node("Ticket 샘플 Ticket 1"));
  expect(faded(container).length).toBeGreaterThan(0);
  expect(node("Ticket 샘플 Ticket 1")).not.toHaveClass("faded");
  fireEvent.mouseLeave(node("Ticket 샘플 Ticket 1"));
  expect(faded(container)).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Entity" }));
  fireEvent.click(node("ip: 203.0.113.10"));
  const chosenFaded = faded(container).length;
  fireEvent.mouseEnter(node("ip: 198.51.100.2"));
  expect(node("ip: 198.51.100.2")).not.toHaveClass("faded");
  expect(node("ip: 203.0.113.10")).toHaveClass("faded");
  fireEvent.mouseLeave(node("ip: 198.51.100.2"));
  expect(faded(container)).toHaveLength(chosenFaded);
  expect(node("ip: 203.0.113.10")).not.toHaveClass("faded");
});

test("a hovered node outside the shown graph still hides nothing and a search dim and a fade are not stacked", () => {
  const { container } = render(<Harness initial="entity" />);
  fireEvent.change(screen.getByRole("textbox", { name: "노드 검색" }), {
    target: { value: "203.0.113.10" },
  });
  fireEvent.mouseEnter(node("ip: 203.0.113.10"));
  expect(nodes(container, "entity")).toHaveLength(60);
  // a dimmed node that is also faded gets one class each and CSS applies the lower opacity only once
  const both = container.querySelectorAll(".incident-graph-node.dim.faded");
  expect(both.length).toBeGreaterThan(0);
});

test("the inspector lists the src and dst entities of the chosen entity as text", () => {
  render(<Harness initial="entity" />);
  fireEvent.click(node("ip: 203.0.113.10"));
  const list = within(inspector()).getByRole("list", {
    name: "이 노드의 연결",
  });
  expect(within(list).getAllByRole("listitem").length).toBeGreaterThan(0);
  expect(within(inspector()).queryByText(/위험 경로|단계/)).toBeNull();
});

test("a node given from the address opens chosen, even one below the top 60", () => {
  render(
    <Harness
      initial="entity"
      start={JSON.stringify(["process", "proc-14.exe"])}
    />,
  );
  expect(node("process: proc-14.exe")).toHaveAttribute("aria-current", "true");
  expect(within(inspector()).getByText("proc-14.exe")).toBeInTheDocument();
});

test("nodes can be chosen with the keyboard", () => {
  render(<Harness />);
  const first = node("Ticket 샘플 Ticket 1");
  expect(first).toHaveAttribute("tabindex", "0");
  fireEvent.keyDown(first, { key: "Enter" });
  expect(within(inspector()).getByText("샘플 Ticket 1")).toBeInTheDocument();
  // Esc clears the choice
  fireEvent.keyDown(node("Ticket 샘플 Ticket 1"), { key: "Escape" });
  expect(screen.queryByRole("button", { name: "선택 해제" })).toBeNull();
  fireEvent.keyDown(node("Ticket 샘플 Ticket 2"), { key: " " });
  expect(within(inspector()).getByText("샘플 Ticket 2")).toBeInTheDocument();
});

test("zoom buttons and Ctrl+wheel zoom, a plain wheel leaves the page scrolling", () => {
  const { container } = render(<Harness />);
  const view = screen.getByRole("region", { name: "Incident 관계도" });
  const start = scale(container);
  fireEvent.click(screen.getByRole("button", { name: "확대" }));
  expect(scale(container)).toBeGreaterThan(start);
  fireEvent.click(screen.getByRole("button", { name: "축소" }));
  expect(scale(container)).toBeCloseTo(start, 5);
  // fireEvent returns false when the page's default was prevented
  expect(fireEvent.wheel(view, { deltaY: -100 })).toBe(true);
  expect(scale(container)).toBeCloseTo(start, 5);
  expect(fireEvent.wheel(view, { deltaY: -100, ctrlKey: true })).toBe(false);
  expect(scale(container)).toBeGreaterThan(start);
  fireEvent.click(screen.getByRole("button", { name: "화면에 맞추기" }));
  expect(scale(container)).toBeCloseTo(start, 5);
});

test("dragging the background pans the view", () => {
  const { container } = render(<Harness />);
  const view = screen.getByRole("region", { name: "Incident 관계도" });
  const world = container.querySelector<HTMLElement>(".incident-graph-world")!;
  const before = world.style.transform;
  fireEvent.pointerDown(view, { clientX: 10, clientY: 10, button: 0 });
  fireEvent.pointerMove(view, { clientX: 70, clientY: 40 });
  fireEvent.pointerUp(view, { clientX: 70, clientY: 40 });
  expect(world.style.transform).not.toBe(before);
});

test("a dragged node stays where it was dropped, without being chosen, and is remembered after leaving the tab", () => {
  render(<Harness />);
  const name = "Ticket 샘플 Ticket 1";
  const left = () => parseFloat(node(name).style.left);
  const start = left();
  fireEvent.pointerDown(node(name), { clientX: 100, clientY: 100, button: 0 });
  fireEvent.pointerMove(node(name), { clientX: 180, clientY: 100 });
  fireEvent.pointerUp(node(name), { clientX: 180, clientY: 100 });
  fireEvent.click(node(name));
  const dropped = left();
  expect(dropped).toBeGreaterThan(start);
  expect(screen.queryByRole("button", { name: "선택 해제" })).toBeNull();
  const tab = screen.getByRole("button", { name: "탭 전환" });
  fireEvent.click(tab);
  fireEvent.click(tab);
  expect(left()).toBeCloseTo(dropped, 5);
});

test("entity values stay literal text, even ones that look like markup or object keys", () => {
  const detail = graphDetail();
  const hostile = {
    type: "url",
    value: '<img src=x onerror="alert(1)">',
    role: "dst",
  };
  detail.alerts[0].entities.push(hostile as never);
  const { container } = render(<Harness detail={detail} initial="entity" />);
  fireEvent.change(screen.getByRole("textbox", { name: "노드 검색" }), {
    target: { value: "onerror" },
  });
  expect(node('url: <img src=x onerror="alert(1)">').textContent).toContain(
    '<img src=x onerror="alert(1)">',
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelectorAll("a")).toHaveLength(0);
  fireEvent.change(screen.getByRole("textbox", { name: "노드 검색" }), {
    target: { value: "__proto__" },
  });
  fireEvent.click(node("user: __proto__"));
  expect(within(inspector()).getByText("__proto__")).toBeInTheDocument();
});

test("shows the asset importance only for an entity that has one", () => {
  render(<Harness initial="entity" />);
  fireEvent.click(node("ip: 198.51.100.2"));
  expect(within(inspector()).getByText("자산 중요도")).toBeInTheDocument();
  expect(within(inspector()).getByText("높음")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
  fireEvent.click(node("ip: 203.0.113.10"));
  expect(within(inspector()).queryByText("자산 중요도")).toBeNull();
});

test("a ticket shows its stored decision as a chip and none before a verdict", () => {
  const { container } = render(<Harness />);
  fireEvent.click(node("Ticket 샘플 Ticket 1"));
  expect(within(inspector()).getByText("malicious")).toHaveClass(
    "badge",
    "decision",
  );
  fireEvent.click(screen.getByRole("button", { name: "선택 해제" }));
  fireEvent.click(node("Ticket 샘플 Ticket 3"));
  expect(
    container.querySelector(".incident-graph-inspector .decision"),
  ).toBeNull();
});

const incident = {
  ...seed.incidents[1],
  ticket_ids: sample.ticket_ids,
} as unknown as IncidentDetail["incident"];
const graphs = sample.ticket_graphs as IncidentDetail["ticket_graphs"];

test("the classification basis is folded and lists the saved paths and states", () => {
  render(<ClassificationBasis incident={incident} ticketGraphs={graphs} />);
  const basis = screen.getByText("분류 근거(고급)").closest("details")!;
  expect(basis).not.toHaveAttribute("open");
  expect(screen.getByText(/분류 당시 후보 없음/)).toBeInTheDocument();
  expect(screen.getByText(/후보 한도로 미완료/)).toBeInTheDocument();
  expect(screen.getByText(/과거 경로 기록 없음/)).toBeInTheDocument();
  expect(screen.getByText(/확인 불가/)).toBeInTheDocument();
  expect(screen.getByText(/공용 IP만 일치해 제외/)).toBeInTheDocument();
  const routes = screen.getByRole("list", { name: "저장된 연결 경로" });
  expect(within(routes).getAllByRole("listitem")).toHaveLength(2);
  expect(routes.textContent).toContain(sample.ticket_ids[1]);
  expect(routes.textContent).toContain("Hunt");
  expect(routes.textContent).toContain("host: lab-7");
});

test("the basis shows a vector-only membership without inventing a path", () => {
  const candidate = {
    ...graphs![0],
    paths: [],
    vector_only: true,
    vector_score: 0.81234,
    representative_ticket_id: sample.ticket_ids[1],
  };
  render(
    <ClassificationBasis incident={incident} ticketGraphs={[candidate]} />,
  );
  expect(
    screen.getByText(
      /유사 Ticket 후보로 연결 \(유사도 0\.812, 그래프 경로 없음\)/,
    ),
  ).toBeInTheDocument();
});

test("the basis shows rejected vector candidates and missing search data", () => {
  const { rerender } = render(
    <ClassificationBasis
      incident={incident}
      ticketGraphs={[
        { ...graphs![0], paths: [], reason: "no_path", candidate_count: 2 },
      ]}
    />,
  );
  expect(
    screen.getByText(/유사 Ticket 후보 검토 완료 \(그래프 경로 없음\)/),
  ).toBeInTheDocument();
  rerender(
    <ClassificationBasis incident={incident} ticketGraphs={undefined} />,
  );
  expect(screen.getByText(/탐색 기록을 받지 못했습니다/)).toBeInTheDocument();
  expect(
    screen.getByText(/현재 Incident로 이어지는 저장 경로가 없습니다/),
  ).toBeInTheDocument();
});

test("the basis keeps external entity text literal", () => {
  const hostile = structuredClone(sample.ticket_graphs);
  hostile[1].paths[0].nodes[2].value = '<img src=x onerror="alert(1)">';
  const { container } = render(
    <ClassificationBasis
      incident={incident}
      ticketGraphs={hostile as IncidentDetail["ticket_graphs"]}
    />,
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain('<img src=x onerror="alert(1)">');
});
