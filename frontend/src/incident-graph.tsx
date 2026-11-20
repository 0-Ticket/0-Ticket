import { useState } from "react";
import { Status } from "./badges";
import type {
  GraphNode,
  IncidentDetail,
  IncidentTicketGraph,
} from "./api/generated/IncidentDetail";

const NODE_WIDTH = 200;
const NODE_HEIGHT = 92;
const COLUMN = 236;
const MARGIN = 24;
const TICKET_Y = 144;
const RECORD_Y = 276;
const RECORD_STEP = 116;
const MARKER_CENTER = 28; // 선은 노드 가운데가 아니라 동그라미 가운데로 이어진다

type Incident = IncidentDetail["incident"];
type SavedPath = { source: string; path: IncidentTicketGraph["paths"][number] };
type PositionedNode = GraphNode & { x: number; y: number };
type PositionedEdge = {
  from: string;
  to: string;
  kind: string;
  relation: "membership" | "path";
};

const nodeKey = (node: GraphNode) => JSON.stringify([node.kind, node.id]);
const nodeName: Record<GraphNode["kind"], string> = {
  ticket: "Ticket",
  alert: "Alert",
  hunt: "Hunt",
  entity: "Entity",
  incident: "Incident",
};

function nodeText(node: GraphNode) {
  return node.kind === "entity"
    ? `${node.type ?? "Entity"}: ${node.value ?? node.id}`
    : `${nodeName[node.kind]} ${node.id}`;
}

function statusText(graph?: IncidentTicketGraph) {
  if (!graph) return "분류 당시 탐색 정보 없음";
  if (graph.coverage === "legacy") return "과거 경로 기록 없음";
  if (graph.coverage === "unknown") return "분류 당시 탐색 상태 확인 불가";
  if (graph.reason === "candidate_limit") return "분류 당시 후보 한도로 미완료";
  if (graph.reason === "public_ip_only")
    return "분류 당시 공용 IP만 일치해 제외";
  if (graph.reason === "no_path") return "분류 당시 후보 없음";
  return graph.coverage === "complete"
    ? "분류 당시 탐색 완료"
    : "분류 당시 탐색 미완료";
}

function buildGraph(incident: Incident, ticketGraphs?: IncidentTicketGraph[]) {
  const ticketIds = [...new Set(incident.ticket_ids)].sort();
  const ticketSet = new Set(ticketIds);
  const savedPaths: SavedPath[] = (ticketGraphs ?? [])
    .filter((graph) => ticketSet.has(graph.ticket_id))
    .flatMap((graph) =>
      graph.paths
        .filter((path) => path.incident_id === incident.id)
        .map((path) => ({ source: graph.ticket_id, path })),
    );
  const nodes = new Map<string, GraphNode>();
  const edges = new Map<string, PositionedEdge>();
  const recordOwners = new Map<string, string>();
  const incidentNode: GraphNode = { kind: "incident", id: incident.id };
  nodes.set(nodeKey(incidentNode), incidentNode);
  for (const id of ticketIds) {
    const ticket: GraphNode = { kind: "ticket", id };
    nodes.set(nodeKey(ticket), ticket);
    const edge: PositionedEdge = {
      from: nodeKey(incidentNode),
      to: nodeKey(ticket),
      kind: "belongs_to",
      relation: "membership",
    };
    edges.set(JSON.stringify([edge.from, edge.to, edge.kind]), edge);
  }

  for (const { source, path } of savedPaths) {
    const pathNodes = new Map<string, GraphNode | null>();
    for (const node of path.nodes) {
      if (
        (node.kind === "incident" && node.id !== incident.id) ||
        (node.kind === "ticket" && !ticketSet.has(node.id))
      )
        continue;
      nodes.set(nodeKey(node), node);
      const previous = pathNodes.get(node.id);
      pathNodes.set(
        node.id,
        previous && previous.kind !== node.kind ? null : node,
      );
    }
    for (const edge of path.edges) {
      if (edge.kind === "belongs_to") continue;
      const from = pathNodes.get(edge.from);
      const to = pathNodes.get(edge.to);
      if (!from || !to) continue;
      const graphEdge: PositionedEdge = {
        from: nodeKey(from),
        to: nodeKey(to),
        kind: edge.kind,
        relation: "path",
      };
      edges.set(
        JSON.stringify([graphEdge.from, graphEdge.to, edge.kind]),
        graphEdge,
      );
      if (from.kind === "ticket" && (to.kind === "alert" || to.kind === "hunt"))
        recordOwners.set(nodeKey(to), from.id);
      if (
        to.kind === "ticket" &&
        (from.kind === "alert" || from.kind === "hunt")
      )
        recordOwners.set(nodeKey(from), to.id);
    }
    for (const node of path.nodes) {
      if (
        (node.kind === "alert" || node.kind === "hunt") &&
        !recordOwners.has(nodeKey(node))
      )
        recordOwners.set(nodeKey(node), source);
    }
  }

  const positions = new Map<string, PositionedNode>();
  const ticketWidth = MARGIN * 2 + Math.max(ticketIds.length, 1) * COLUMN;
  positions.set(nodeKey(incidentNode), {
    ...incidentNode,
    x: MARGIN,
    y: MARGIN,
  });
  const ticketColumns = new Map(ticketIds.map((id, index) => [id, index]));
  for (const id of ticketIds) {
    const node = nodes.get(nodeKey({ kind: "ticket", id }))!;
    positions.set(nodeKey(node), {
      ...node,
      x: MARGIN + ticketColumns.get(id)! * COLUMN,
      y: TICKET_Y,
    });
  }

  const recordGroups = new Map<string, GraphNode[]>();
  for (const node of nodes.values()) {
    if (node.kind !== "alert" && node.kind !== "hunt") continue;
    const owner = recordOwners.get(nodeKey(node)) ?? ticketIds[0];
    const group = recordGroups.get(owner) ?? [];
    group.push(node);
    recordGroups.set(owner, group);
  }
  let maxRecords = 0;
  for (const [owner, group] of recordGroups) {
    group.sort((a, b) => nodeKey(a).localeCompare(nodeKey(b)));
    maxRecords = Math.max(maxRecords, group.length);
    for (const [index, node] of group.entries()) {
      positions.set(nodeKey(node), {
        ...node,
        x: MARGIN + (ticketColumns.get(owner) ?? 0) * COLUMN,
        y: RECORD_Y + index * RECORD_STEP,
      });
    }
  }

  const entityY = RECORD_Y + maxRecords * RECORD_STEP + 48;
  const entityNodes = [...nodes.values()].filter(
    (node) => node.kind === "entity",
  );
  const positionedEdges = [...edges.values()];
  const preferredX = (entity: GraphNode) => {
    const connected = positionedEdges
      .filter(
        (edge) => edge.from === nodeKey(entity) || edge.to === nodeKey(entity),
      )
      .map((edge) =>
        positions.get(edge.from === nodeKey(entity) ? edge.to : edge.from),
      )
      .filter((node): node is PositionedNode => node !== undefined);
    return connected.length
      ? connected.reduce((sum, node) => sum + node.x + NODE_WIDTH / 2, 0) /
          connected.length -
          NODE_WIDTH / 2
      : MARGIN;
  };
  entityNodes.sort(
    (a, b) =>
      preferredX(a) - preferredX(b) || nodeKey(a).localeCompare(nodeKey(b)),
  );
  let entityRight = MARGIN;
  for (const entity of entityNodes) {
    const x = Math.max(MARGIN, preferredX(entity), entityRight);
    positions.set(nodeKey(entity), { ...entity, x, y: entityY });
    entityRight = x + NODE_WIDTH + MARGIN;
  }
  return {
    nodes: [...positions.values()],
    edges: positionedEdges.filter(
      (edge) => positions.has(edge.from) && positions.has(edge.to),
    ),
    paths: savedPaths,
    width: Math.max(360, ticketWidth, entityRight + MARGIN),
    height: entityNodes.length
      ? entityY + NODE_HEIGHT + MARGIN
      : maxRecords
        ? RECORD_Y + maxRecords * RECORD_STEP + MARGIN
        : TICKET_Y + NODE_HEIGHT + MARGIN,
  };
}

type Edge = PositionedEdge;

// Nodes reachable through saved search paths only (membership lines are not evidence of sharing).
function reach(start: string, edges: Edge[]) {
  const seen = new Set([start]);
  const queue = [start];
  while (queue.length) {
    const at = queue.shift()!;
    for (const edge of edges) {
      if (edge.relation !== "path") continue;
      const next =
        edge.from === at ? edge.to : edge.to === at ? edge.from : null;
      if (next && !seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return seen;
}

export function IncidentGraph({
  incident,
  ticketGraphs,
  titles,
}: {
  incident: Incident;
  ticketGraphs?: IncidentTicketGraph[];
  // Ticket titles by id (IncidentDetail.tickets). Without them nodes show the id.
  titles?: Record<string, string>;
}) {
  const graph = buildGraph(incident, ticketGraphs);
  const positioned = new Map(graph.nodes.map((node) => [nodeKey(node), node]));
  const byTicket = new Map(ticketGraphs?.map((item) => [item.ticket_id, item]));
  const incidentKey = nodeKey({ kind: "incident", id: incident.id });
  const [selected, setSelected] = useState(incidentKey);
  const [hovered, setHovered] = useState<string | null>(null);
  // Only hovering (or keyboard focus) dims the rest; the selected node just gets a ring.
  const linked = new Set(hovered ? [hovered] : []);
  for (const edge of graph.edges) {
    if (edge.from === hovered) linked.add(edge.to);
    if (edge.to === hovered) linked.add(edge.from);
  }
  const label = (node: GraphNode) =>
    node.kind === "incident"
      ? incident.title || node.id
      : node.kind === "ticket"
        ? (titles?.[node.id] ?? node.id)
        : node.kind === "entity"
          ? (node.value ?? node.id)
          : node.id;
  const chosen = positioned.get(selected) ?? positioned.get(incidentKey)!;
  const scope =
    chosen.kind === "incident"
      ? new Set(graph.nodes.map(nodeKey))
      : reach(nodeKey(chosen), graph.edges);
  const inScope = graph.nodes.filter((node) => scope.has(nodeKey(node)));
  const otherTickets = inScope.filter(
    (node) => node.kind === "ticket" && nodeKey(node) !== nodeKey(chosen),
  ).length;
  const alerts = inScope.filter((node) => node.kind === "alert").length;
  const select = (key: string) => setSelected(key);
  return (
    <section className="incident-graph">
      <div className="incident-graph-heading">
        <div>
          <strong>{incident.title || incident.id}</strong>
          <span>{incident.id}</span>
        </div>
        <div className="incident-graph-chips">
          <Status value={incident.status} />
          <span className="badge">Ticket {incident.ticket_ids.length}</span>
        </div>
      </div>
      <div className="incident-graph-modebar">
        <span>그래프 보기 전환</span>
        <div role="group" aria-label="그래프 보기">
          <button type="button" aria-pressed="true">
            Ticket
          </button>
          <button
            type="button"
            aria-pressed="false"
            disabled
            title="Entity 공격 경로 보기는 아직 제공하지 않습니다"
          >
            Entity
          </button>
        </div>
      </div>
      <p className="incident-graph-note">
        선은 저장된 후보 탐색 경로입니다. 공격 순서나 최종 선택 이유를 뜻하지
        않습니다.
      </p>
      <div className="incident-graph-legend" aria-label="관계선 범례">
        <span className="membership">Incident 소속</span>
        <span className="path">공유 엔티티 연결</span>
        <span className="dot incident">Incident</span>
        <span className="dot ticket">Ticket</span>
      </div>
      <p className="incident-graph-scroll-hint">
        관계도 안에서 가로로 스크롤하거나 키보드로 이동할 수 있습니다. 노드에
        마우스를 올리면 연결이 강조되고, 클릭하면 상세 정보가 표시됩니다.
      </p>
      <div
        className="incident-graph-viewport"
        role="region"
        aria-label="Incident 관계도"
        tabIndex={0}
      >
        <div
          className="incident-graph-canvas"
          style={{ width: graph.width, height: graph.height }}
        >
          <svg
            className="incident-graph-lines"
            width={graph.width}
            height={graph.height}
            aria-hidden="true"
          >
            {graph.edges.map((edge) => {
              const from = positioned.get(edge.from)!;
              const to = positioned.get(edge.to)!;
              const x1 = from.x + NODE_WIDTH / 2;
              const y1 = from.y + MARKER_CENTER;
              const x2 = to.x + NODE_WIDTH / 2;
              const y2 = to.y + MARKER_CENTER;
              // 선 하나만 봐도 무엇을 공유해 이어졌는지 읽히게 가운데에 엔티티를 적는다.
              const entity =
                from.kind === "entity"
                  ? from
                  : to.kind === "entity"
                    ? to
                    : null;
              const touches =
                hovered === null ||
                edge.from === hovered ||
                edge.to === hovered;
              return (
                <g
                  key={JSON.stringify([edge.from, edge.to, edge.kind])}
                  className={touches ? "on" : "dim"}
                >
                  <line
                    data-relation={edge.relation}
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                  />
                  {edge.relation === "path" && entity ? (
                    <text
                      className="incident-graph-edge-label"
                      x={(x1 + x2) / 2}
                      y={(y1 + y2) / 2}
                    >
                      {nodeText(entity)}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </svg>
          {graph.nodes.map((node) => {
            const key = nodeKey(node);
            return (
              <div
                key={key}
                className={[
                  "incident-graph-node",
                  node.kind,
                  key === selected ? "selected" : "",
                  hovered === null || linked.has(key) ? "" : "dim",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={{ left: node.x, top: node.y }}
                role="group"
                tabIndex={0}
                aria-label={nodeText(node)}
                aria-current={key === selected ? "true" : undefined}
                onMouseEnter={() => setHovered(key)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(key)}
                onBlur={() => setHovered(null)}
                onClick={() => select(key)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    select(key);
                  }
                }}
              >
                <i className="marker" aria-hidden="true" />
                <strong>
                  {node.kind === "entity"
                    ? (node.type ?? "Entity")
                    : nodeName[node.kind]}
                </strong>
                <span>{label(node)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <aside className="incident-graph-inspector" aria-label="선택된 노드">
        <span className="eyebrow">
          선택된 노드 · {nodeName[chosen.kind].toUpperCase()}
        </span>
        <h4>{label(chosen)}</h4>
        <code>
          {chosen.kind === "entity" ? (chosen.type ?? "") : chosen.id}
        </code>
        <dl>
          <div>
            <dt>연결 Ticket</dt>
            <dd>
              {chosen.kind === "incident"
                ? incident.ticket_ids.length
                : otherTickets}
            </dd>
          </div>
          <div>
            <dt>관련 Alert</dt>
            <dd>{alerts}</dd>
          </div>
          <div>
            <dt>자산 중요도</dt>
            <dd>—</dd>
          </div>
        </dl>
      </aside>
      {ticketGraphs === undefined || ticketGraphs.length === 0 ? (
        <p className="incident-graph-empty">
          Ticket별 탐색 기록을 받지 못했습니다.
        </p>
      ) : null}
      {graph.paths.length === 0 ? (
        <p className="incident-graph-empty">
          현재 Incident로 이어지는 저장 경로가 없습니다. Ticket 소속은 별도로
          표시합니다.
        </p>
      ) : (
        <>
          <h4>저장된 연결 경로</h4>
          <ol className="incident-graph-routes" aria-label="저장된 연결 경로">
            {graph.paths.map(({ source, path }, index) => (
              <li key={`${source}-${path.ticket_id}-${index}`}>
                {[
                  `출발 Ticket ${source}`,
                  ...path.nodes
                    .slice(1)
                    .filter((node) => node.kind !== "incident")
                    .map(nodeText),
                ].join(" → ")}
              </li>
            ))}
          </ol>
        </>
      )}
      <h4>Ticket별 분류 당시 탐색 상태</h4>
      <ul className="incident-graph-statuses">
        {incident.ticket_ids.map((id) => (
          <li key={id}>
            {titles?.[id] && <span className="status-title">{titles[id]}</span>}
            <span>{id}</span>
            <strong>{statusText(byTicket.get(id))}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}
