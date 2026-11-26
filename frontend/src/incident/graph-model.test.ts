import { expect, test } from "vitest";
import {
  ENTITY_CAP,
  buildGraph,
  facts,
  arrowLinks,
  directNeighbours,
  type GNode,
} from "./graph-model";
import { graphDetail } from "./graph-sample";

const detail = graphDetail();
const none = {
  expanded: new Set<string>(),
  types: new Set<string>(),
  query: "",
};
const entity = (type: string, value: string) =>
  JSON.stringify(["entity", type, value]);
const values = (nodes: GNode[]) => nodes.map((n) => n.value);

test("the entity view keeps only the top 60 by connections and says how many are hidden", () => {
  const graph = buildGraph(detail, "entity", none);
  expect(graph.total).toBe(104);
  expect(graph.nodes).toHaveLength(ENTITY_CAP);
  expect(graph.hidden).toBe(44);
  // The shared sources are the most connected; hunt-only entities have no connection.
  expect(values(graph.nodes)).toContain("203.0.113.10");
  expect(values(graph.nodes)).not.toContain("hunt.example.com");
});

test("equal connection counts are ordered by type then value, so the cut is stable", () => {
  const a = buildGraph(detail, "entity", none).nodes.map((n) => n.key);
  const b = buildGraph(detail, "entity", none).nodes.map((n) => n.key);
  expect(a).toEqual(b);
  expect(a).not.toContain(entity("process", "proc-14.exe"));
});

test("an arrow runs from a src entity to each dst entity of the same alert, and only there", () => {
  const graph = buildGraph(detail, "entity", { ...none, limit: 1000 });
  const arrows = graph.edges.filter((e) => e.arrow);
  expect(arrows).toHaveLength(42);
  const first = arrows.find(
    (e) =>
      e.from === entity("ip", "203.0.113.11") &&
      e.to === entity("ip", "198.51.100.2"),
  );
  expect(first).toBeDefined();
  expect(
    arrows.some((e) => e.to === entity("ip", "203.0.113.10") && e.arrow),
  ).toBe(false);
  // user and host roles never make an arrow
  expect(
    arrows.some((e) => e.from.includes('"user"') || e.from.includes('"host"')),
  ).toBe(false);
});

test("entities of one alert are joined once, and a pair that has an arrow has no second plain line", () => {
  const graph = buildGraph(detail, "entity", { ...none, limit: 1000 });
  const pair = (a: string, b: string) =>
    graph.edges.filter(
      (e) => (e.from === a && e.to === b) || (e.from === b && e.to === a),
    );
  expect(pair(entity("user", "user-1"), entity("host", "srv-1"))).toHaveLength(
    1,
  );
  const src = entity("ip", "203.0.113.11");
  const dst = entity("ip", "198.51.100.2");
  expect(pair(src, dst)).toHaveLength(1);
  expect(pair(src, dst)[0].arrow).toBe(true);
  // 9 entities in an alert: 36 pairs; 14 alerts, the shared ones are merged
  expect(graph.edges.length).toBeLessThan(14 * 36);
});

test("entities of a ticket without alerts are nodes but are never joined to each other", () => {
  const graph = buildGraph(detail, "entity", { ...none, limit: 1000 });
  const hunt = entity("domain", "hunt.example.com");
  expect(graph.nodes.map((n) => n.key)).toContain(hunt);
  expect(graph.edges.some((e) => e.from === hunt || e.to === hunt)).toBe(false);
});

test("the type filter re-ranks inside that type and hides the others", () => {
  const graph = buildGraph(detail, "entity", {
    ...none,
    types: new Set(["ip"]),
  });
  expect(new Set(graph.nodes.map((n) => n.type))).toEqual(new Set(["ip"]));
  expect(graph.nodes).toHaveLength(18);
  expect(graph.hidden).toBe(0);
});

test("a search brings in matches below the top 60 and keeps the others where they were", () => {
  const before = buildGraph(detail, "entity", none).nodes.map((n) => n.key);
  const graph = buildGraph(detail, "entity", { ...none, query: "proc-14" });
  const after = graph.nodes.map((n) => n.key);
  expect(after).toContain(entity("process", "proc-14.exe"));
  expect(after.slice(0, before.length)).toEqual(before);
});

test("an entity value that looks like an object key stays an ordinary node", () => {
  const graph = buildGraph(detail, "entity", { ...none, query: "__proto__" });
  const node = graph.nodes.find((n) => n.value === "__proto__");
  expect(node?.label).toBe("__proto__");
  expect(node?.type).toBe("user");
});

test("the ticket view folds alerts into their ticket and unfolds the ones asked for", () => {
  const folded = buildGraph(detail, "ticket", none);
  expect(folded.nodes.filter((n) => n.kind === "alert")).toHaveLength(0);
  expect(folded.nodes.filter((n) => n.kind === "ticket")).toHaveLength(14);
  expect(folded.nodes.filter((n) => n.kind === "incident")).toHaveLength(1);
  const ticket = detail.tickets[12].id;
  const open = buildGraph(detail, "ticket", {
    ...none,
    expanded: new Set([ticket]),
  });
  const alerts = open.nodes.filter((n) => n.kind === "alert");
  expect(alerts).toHaveLength(2);
  const ticketKey = JSON.stringify(["ticket", ticket]);
  expect(open.edges.filter((e) => e.from === ticketKey)).toHaveLength(2);
  // its entities hang on the alerts now, not on the ticket
  const reach = new Set(alerts.map((a) => a.key));
  const own = open.edges.filter((e) => e.from === ticketKey);
  expect(own.every((e) => reach.has(e.to))).toBe(true);
});

test("the ticket view filters entities by type but always keeps incident, tickets and alerts", () => {
  const graph = buildGraph(detail, "ticket", {
    ...none,
    types: new Set(["url"]),
  });
  expect(
    new Set(graph.nodes.filter((n) => n.kind === "entity").map((n) => n.type)),
  ).toEqual(new Set(["url"]));
  expect(graph.nodes.filter((n) => n.kind === "ticket")).toHaveLength(14);
});

test("direct neighbours are the nodes a line reaches, and nothing is removed from the graph", () => {
  const graph = buildGraph(detail, "entity", none);
  const hub = entity("ip", "203.0.113.10");
  const near = directNeighbours(graph, hub);
  expect(near.has(hub)).toBe(true);
  const touching = graph.edges.filter((e) => e.from === hub || e.to === hub);
  expect(near.size).toBe(touching.length + 1);
  expect(near.size).toBeLessThan(graph.nodes.length);
});

test("a node chosen from outside the top 60 is added without moving the others", () => {
  const key = entity("process", "proc-14.exe");
  const base = buildGraph(detail, "entity", none);
  expect(base.nodes.some((n) => n.key === key)).toBe(false);
  const withIt = buildGraph(detail, "entity", { ...none, include: key });
  expect(withIt.nodes.slice(0, base.nodes.length)).toEqual(base.nodes);
  expect(withIt.nodes.some((n) => n.key === key)).toBe(true);
});

test("arrow links list the src and dst entities an entity is joined to by the whole response", () => {
  const hub = entity("ip", "203.0.113.10");
  const links = arrowLinks(detail, hub);
  expect(links.to.length + links.from.length).toBeGreaterThan(0);
  expect(links.to.every((n) => n.kind === "entity")).toBe(true);
  expect(arrowLinks(detail, entity("user", "__proto__")).to).toEqual([]);
});

test("facts count what an entity is connected to from the whole response", () => {
  const hub = buildGraph(detail, "entity", none).nodes.find(
    (n) => n.value === "203.0.113.10",
  )!;
  expect(facts(detail, hub)).toEqual([
    ["연결 Ticket", 4],
    ["연결 Alert", 4],
  ]);
  const incident = buildGraph(detail, "ticket", none).nodes[0];
  expect(facts(detail, incident)[0]).toEqual(["Ticket", 14]);
});
