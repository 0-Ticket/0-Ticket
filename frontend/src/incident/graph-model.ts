import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { when } from "./model";

export type GraphView = "ticket" | "entity";
export type GNode = {
  key: string;
  kind: "incident" | "ticket" | "alert" | "entity";
  id: string;
  label: string;
  type?: string;
  value?: string;
};
// An arrow runs from `from` to `to` (a src entity to a dst entity of one alert); a plain line has no direction.
export type GEdge = { key: string; from: string; to: string; arrow: boolean };
export type Graph = {
  nodes: GNode[];
  edges: GEdge[];
  // Entities left out by the cap, out of all entities (the entity view only).
  hidden: number;
  total: number;
  types: string[];
};
export type GraphOptions = {
  expanded: Set<string>;
  types: Set<string>;
  query: string;
  limit?: number;
};

export const ENTITY_CAP = 60;

type Entity = { type: string; value: string; role?: string | null };

// Keys are JSON strings, never object keys, so a hostile entity value like "__proto__" is just text.
const entityKey = (e: Entity) => JSON.stringify(["entity", e.type, e.value]);
const edgeOf = (from: string, to: string, arrow: boolean): GEdge => ({
  key: JSON.stringify([from, to]),
  from,
  to,
  arrow,
});
const entityNode = (e: Entity): GNode => ({
  key: entityKey(e),
  kind: "entity",
  id: e.value,
  label: e.value,
  type: e.type,
  value: e.value,
});

export function matches(node: GNode, query: string) {
  const needle = query.trim().toLowerCase();
  return (
    needle === "" ||
    [node.label, node.id, node.type ?? ""].some((text) =>
      text.toLowerCase().includes(needle),
    )
  );
}

function ticketGraph(detail: IncidentDetail, o: GraphOptions): Graph {
  const alertsById = new Map(detail.alerts.map((a) => [a.id, a]));
  const incident: GNode = {
    key: JSON.stringify(["incident", detail.incident.id]),
    kind: "incident",
    id: detail.incident.id,
    label: detail.incident.title || detail.incident.id,
  };
  const nodes = new Map<string, GNode>([[incident.key, incident]]);
  const edges = new Map<string, GEdge>();
  const link = (from: string, to: string) => {
    const edge = edgeOf(from, to, false);
    edges.set(edge.key, edge);
  };
  const types = new Set<string>();
  for (const ticket of detail.tickets) {
    const node: GNode = {
      key: JSON.stringify(["ticket", ticket.id]),
      kind: "ticket",
      id: ticket.id,
      label: ticket.title || ticket.id,
    };
    nodes.set(node.key, node);
    link(incident.key, node.key);
    // Alerts only appear once their ticket is unfolded; until then the ticket holds the entities itself.
    const alerts = o.expanded.has(ticket.id)
      ? ticket.alert_ids.flatMap((id) => alertsById.get(id) ?? [])
      : [];
    const holders = new Map<string, string>();
    for (const alert of alerts) {
      const alertNode: GNode = {
        key: JSON.stringify(["alert", alert.id]),
        kind: "alert",
        id: alert.id,
        label: `${when(alert.time)} · 엔티티 ${alert.entities.length}개`,
      };
      nodes.set(alertNode.key, alertNode);
      link(node.key, alertNode.key);
      for (const e of alert.entities) holders.set(entityKey(e), alertNode.key);
    }
    const hold = (e: Entity) => {
      types.add(e.type);
      if (o.types.size && !o.types.has(e.type)) return;
      const en = entityNode(e);
      nodes.set(en.key, en);
      link(holders.get(en.key) ?? node.key, en.key);
    };
    if (alerts.length) {
      for (const alert of alerts) alert.entities.forEach(hold);
      // Entities the ticket has that none of its alerts carry stay on the ticket.
      for (const e of ticket.entities) if (!holders.has(entityKey(e))) hold(e);
    } else ticket.entities.forEach(hold);
  }
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    hidden: 0,
    total: [...nodes.values()].filter((n) => n.kind === "entity").length,
    types: [...types].sort(),
  };
}

function entityGraph(detail: IncidentDetail, o: GraphOptions): Graph {
  const pool = new Map<string, GNode>();
  const near = new Map<string, Set<string>>();
  const arrows = new Map<string, GEdge>();
  const plain = new Map<string, GEdge>();
  const add = (e: Entity) => {
    const node = entityNode(e);
    pool.set(node.key, node);
    if (!near.has(node.key)) near.set(node.key, new Set());
    return node.key;
  };
  // Entities are joined only through the alert they appeared in together.
  for (const alert of detail.alerts) {
    const keys = [...new Set(alert.entities.map(add))];
    for (const a of keys)
      for (const b of keys)
        if (a < b) {
          near.get(a)!.add(b);
          near.get(b)!.add(a);
          const edge = edgeOf(a, b, false);
          plain.set(edge.key, edge);
        }
    const role = (r: string) => [
      ...new Set(
        alert.entities.filter((e) => e.role === r).map((e) => entityKey(e)),
      ),
    ];
    for (const from of role("src"))
      for (const to of role("dst"))
        if (from !== to) {
          const edge = edgeOf(from, to, true);
          arrows.set(edge.key, edge);
        }
  }
  // Entities of tickets with no alert are nodes without lines.
  for (const ticket of detail.tickets) ticket.entities.forEach(add);
  const types = [...new Set([...pool.values()].map((n) => n.type!))].sort();
  const allowed = [...pool.values()].filter(
    (n) => !o.types.size || o.types.has(n.type!),
  );
  allowed.sort(
    (a, b) =>
      near.get(b.key)!.size - near.get(a.key)!.size ||
      a.type!.localeCompare(b.type!) ||
      a.value!.localeCompare(b.value!),
  );
  const top = allowed.slice(0, o.limit ?? ENTITY_CAP);
  const shown = new Set(top.map((n) => n.key));
  // Matches below the cut are added after the top ones, so the others keep their place.
  const extra = o.query.trim()
    ? allowed.filter((n) => !shown.has(n.key) && matches(n, o.query))
    : [];
  const nodes = [...top, ...extra];
  const visible = new Set(nodes.map((n) => n.key));
  const edges = [...arrows.values(), ...plain.values()].filter(
    (e) =>
      visible.has(e.from) &&
      visible.has(e.to) &&
      // a pair with an arrow in either direction needs no second plain line
      (e.arrow ||
        (!arrows.has(JSON.stringify([e.from, e.to])) &&
          !arrows.has(JSON.stringify([e.to, e.from])))),
  );
  return {
    nodes,
    edges,
    hidden: allowed.length - nodes.length,
    total: pool.size,
    types,
  };
}

export function buildGraph(
  detail: IncidentDetail,
  view: GraphView,
  options: GraphOptions,
): Graph {
  return view === "ticket"
    ? ticketGraph(detail, options)
    : entityGraph(detail, options);
}

// The chosen node, its direct neighbours, and only the lines that touch it.
export function neighbourhood(graph: Graph, key: string): Graph {
  const edges = graph.edges.filter((e) => e.from === key || e.to === key);
  const keep = new Set([key, ...edges.flatMap((e) => [e.from, e.to])]);
  return {
    ...graph,
    nodes: graph.nodes.filter((n) => keep.has(n.key)),
    edges,
  };
}

// Counts for the inspector, taken from the whole response and not from what the filters leave visible.
export function facts(detail: IncidentDetail, node: GNode): [string, number][] {
  const alertsById = new Map(detail.alerts.map((a) => [a.id, a]));
  if (node.kind === "incident")
    return [
      ["Ticket", detail.tickets.length],
      ["Alert", detail.alerts.length],
      ["엔티티", detail.incident.entities.length],
    ];
  if (node.kind === "ticket") {
    const ticket = detail.tickets.find((t) => t.id === node.id);
    return [
      [
        "관련 Alert",
        ticket?.alert_ids.filter((id) => alertsById.has(id)).length ?? 0,
      ],
      ["엔티티", ticket?.entities.length ?? 0],
    ];
  }
  if (node.kind === "alert")
    return [
      ["엔티티", alertsById.get(node.id)?.entities.length ?? 0],
      [
        "소속 Ticket",
        detail.tickets.filter((t) => t.alert_ids.includes(node.id)).length,
      ],
    ];
  const has = (list: Entity[]) => list.some((e) => entityKey(e) === node.key);
  const owners = detail.tickets.filter(
    (t) =>
      has(t.entities) ||
      t.alert_ids.some((id) => has(alertsById.get(id)?.entities ?? [])),
  );
  return [
    ["연결 Ticket", owners.length],
    ["연결 Alert", detail.alerts.filter((a) => has(a.entities)).length],
  ];
}
