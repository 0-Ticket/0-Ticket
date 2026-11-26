import type {
  GraphNode,
  IncidentDetail,
  IncidentTicketGraph,
} from "../api/generated/IncidentDetail";
import { statusText } from "./model";

type Incident = IncidentDetail["incident"];

const nodeName: Record<GraphNode["kind"], string> = {
  ticket: "Ticket",
  alert: "Alert",
  hunt: "Hunt",
  entity: "Entity",
  incident: "Incident",
};

const nodeText = (node: GraphNode) =>
  node.kind === "entity"
    ? `${node.type ?? "Entity"}: ${node.value ?? node.id}`
    : `${nodeName[node.kind]} ${node.id}`;

// What the classifier saw when it put each Ticket here: the saved search paths and the state of each search.
// The graph above does not draw these paths; it is built from the Tickets, Alerts and entities themselves.
export function ClassificationBasis({
  incident,
  ticketGraphs,
  titles,
}: {
  incident: Incident;
  ticketGraphs?: IncidentTicketGraph[];
  titles?: Record<string, string>;
}) {
  const byTicket = new Map(ticketGraphs?.map((item) => [item.ticket_id, item]));
  const ticketSet = new Set(incident.ticket_ids);
  const paths = (ticketGraphs ?? [])
    .filter((graph) => ticketSet.has(graph.ticket_id))
    .flatMap((graph) =>
      graph.paths
        .filter((path) => path.incident_id === incident.id)
        .map((path) => ({ source: graph.ticket_id, path })),
    );
  return (
    <section className="incident-graph">
      {ticketGraphs === undefined || ticketGraphs.length === 0 ? (
        <p className="incident-graph-empty">
          Ticket별 탐색 기록을 받지 못했습니다.
        </p>
      ) : null}
      <details className="incident-graph-basis">
        <summary>분류 근거(고급)</summary>
        {paths.length === 0 ? (
          <p className="incident-graph-empty">
            현재 Incident로 이어지는 저장 경로가 없습니다. Ticket 소속은 별도로
            표시합니다.
          </p>
        ) : (
          <>
            <h4>저장된 연결 경로</h4>
            <ol className="incident-graph-routes" aria-label="저장된 연결 경로">
              {paths.map(({ source, path }, index) => (
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
              {titles?.[id] && (
                <span className="status-title">{titles[id]}</span>
              )}
              <span>{id}</span>
              <strong>{statusText(byTicket.get(id))}</strong>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
