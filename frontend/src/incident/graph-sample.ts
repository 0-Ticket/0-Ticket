import sample from "../../../tests/fixtures/frontend/incident_graph_entities.json";
import type { IncidentDetail } from "../api/generated/IncidentDetail";

// Test helper: a response built from the hand-made sample, with the incident's entity list derived from it.
export function graphDetail(
  override: Partial<IncidentDetail> = {},
): IncidentDetail {
  const tickets = structuredClone(sample.tickets);
  const alerts = structuredClone(sample.alerts);
  const entities = new Map(
    [...tickets, ...alerts]
      .flatMap((item) => item.entities)
      .map((e) => [JSON.stringify([e.type, e.value]), e]),
  );
  return {
    incident: {
      id: "inc_01a19f93-1266-7000-8000-000000000001",
      title: "샘플 Incident",
      status: "awaiting_review",
      severity: 5,
      assessed_severity: 5,
      ticket_ids: tickets.map((t) => t.id),
      entities: [...entities.values()],
    },
    tickets,
    alerts,
    artifacts: [],
    proposals: [],
    ticket_graphs: [],
    entity_criticality: sample.entity_criticality,
    seed_source: null,
    ...override,
  } as unknown as IncidentDetail;
}
