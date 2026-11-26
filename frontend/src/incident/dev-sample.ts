import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { graphDetail } from "./graph-sample";

// Development only (loaded through a dynamic import under import.meta.env.DEV): browser samples for the screens
// the server cannot produce: 104 entities, and an Incident with no Ticket, which the contract forbids (ticket_ids >= 1).
export function devSample(kind: "graph" | "empty", id: string): IncidentDetail {
  const sample = graphDetail();
  if (kind === "graph")
    return { ...sample, incident: { ...sample.incident, id } };
  return {
    ...sample,
    // the contract type forbids an empty list, which is exactly the case this sample shows
    incident: {
      ...sample.incident,
      id,
      ticket_ids: [] as unknown as IncidentDetail["incident"]["ticket_ids"],
      entities: [],
    },
    tickets: [],
    alerts: [],
    entity_criticality: [],
  };
}
