import type {
  IncidentDetail,
  IncidentTicketGraph,
} from "../api/generated/IncidentDetail";

export const when = (ms: number) => new Date(ms).toLocaleString("ko-KR");

export type Ticket = IncidentDetail["tickets"][number];
export type Dir = "asc" | "desc";
export type TicketSort =
  "severity" | "created_at" | "evidence_count" | "decision";
export type EntitySort = "type" | "tickets" | "first";

const entityKey = (e: { type: string; value: string }) =>
  JSON.stringify([e.type, e.value]);

export function decisionCounts(tickets: Ticket[]) {
  const counts = { malicious: 0, undetermined: 0, benign: 0, pending: 0 };
  for (const t of tickets) counts[t.decision ?? "pending"] += 1;
  return counts;
}

export type EntityRow = {
  key: string;
  type: string;
  value: string;
  role: string | null;
  tickets: number;
  alerts: number;
  first: number | null;
};

// The Ticket/Alert counts and first sighting come from the entities each Ticket and Alert holds.
// The first sighting is the earliest Alert time; with no Alert it falls back to the Ticket creation time.
export function entityRows(detail: IncidentDetail): EntityRow[] {
  const alertsById = new Map(detail.alerts.map((a) => [a.id, a]));
  const seen = new Map<
    string,
    {
      tickets: Set<string>;
      alerts: Set<string>;
      alertAt: number[];
      ticketAt: number[];
    }
  >();
  const slot = (key: string) => {
    let item = seen.get(key);
    if (!item) {
      item = {
        tickets: new Set(),
        alerts: new Set(),
        alertAt: [],
        ticketAt: [],
      };
      seen.set(key, item);
    }
    return item;
  };
  for (const ticket of detail.tickets) {
    for (const entity of ticket.entities) {
      const item = slot(entityKey(entity));
      item.tickets.add(ticket.id);
      item.ticketAt.push(ticket.created_at);
    }
    for (const alertId of ticket.alert_ids) {
      const alert = alertsById.get(alertId);
      if (!alert) continue;
      for (const entity of alert.entities) {
        const item = slot(entityKey(entity));
        item.tickets.add(ticket.id);
        item.alerts.add(alert.id);
        item.alertAt.push(alert.time);
      }
    }
  }
  return detail.incident.entities.map((entity) => {
    const item = seen.get(entityKey(entity));
    const times = item?.alertAt.length ? item.alertAt : (item?.ticketAt ?? []);
    return {
      key: entityKey(entity) + (entity.role ?? ""),
      type: entity.type,
      value: entity.value,
      role: entity.role,
      tickets: item?.tickets.size ?? 0,
      alerts: item?.alerts.size ?? 0,
      first: times.length ? Math.min(...times) : null,
    };
  });
}

export function searchTickets(tickets: Ticket[], query: string) {
  const needle = query.trim().toLowerCase();
  return needle
    ? tickets.filter(
        (t) =>
          t.title.toLowerCase().includes(needle) ||
          t.id.toLowerCase().includes(needle),
      )
    : tickets;
}

const rank = { malicious: 0, undetermined: 1, benign: 2 } as const;
const decisionRank = (t: Ticket) => (t.decision ? rank[t.decision] : 3);

export function sortTickets(tickets: Ticket[], key: TicketSort, dir: Dir) {
  const value = (t: Ticket) => (key === "decision" ? decisionRank(t) : t[key]);
  const sign = dir === "asc" ? 1 : -1;
  return [...tickets].sort((a, b) => sign * (value(a) - value(b)));
}

export function sortEntities(rows: EntityRow[], key: EntitySort, dir: Dir) {
  const sign = dir === "asc" ? 1 : -1;
  const value = (r: EntityRow) =>
    key === "type" ? r.type : key === "tickets" ? r.tickets : (r.first ?? 0);
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    return (
      sign *
      (typeof x === "string" ? x.localeCompare(String(y)) : x - Number(y))
    );
  });
}

export function paginate<T>(rows: T[], page: number, size: number) {
  const pages = Math.max(Math.ceil(rows.length / size), 1);
  const current = Math.min(Math.max(page, 1), pages);
  return {
    rows: rows.slice((current - 1) * size, current * size),
    page: current,
    pages,
  };
}

export function statusText(graph?: IncidentTicketGraph) {
  if (!graph) return "분류 당시 탐색 정보 없음";
  if (graph.coverage === "legacy") return "과거 경로 기록 없음";
  if (graph.coverage === "unknown") return "분류 당시 탐색 상태 확인 불가";
  if (graph.vector_only)
    return `유사 Ticket 후보로 연결 (유사도 ${graph.vector_score?.toFixed(3) ?? "확인 불가"}, 그래프 경로 없음)`;
  if ((graph.candidate_count ?? 0) > 0 && graph.reason === "no_path")
    return "유사 Ticket 후보 검토 완료 (그래프 경로 없음)";
  if (graph.reason === "no_similar_candidate")
    return "분류 당시 유사 Ticket 후보 없음";
  if (graph.reason === "index_pending") return "분류용 색인 대기 중";
  if (graph.reason === "candidate_limit") return "분류 당시 후보 한도로 미완료";
  if (graph.reason === "public_ip_only")
    return "분류 당시 공용 IP만 일치해 제외";
  if (graph.reason === "no_path") return "분류 당시 후보 없음";
  return graph.coverage === "complete"
    ? "분류 당시 탐색 완료"
    : "분류 당시 탐색 미완료";
}

export function latestArtifact(artifacts: IncidentDetail["artifacts"]) {
  return artifacts.reduce<(typeof artifacts)[number] | null>(
    (a, b) => (a === null || b.analysis_round > a.analysis_round ? b : a),
    null,
  );
}

export function nextSort<K extends string>(
  current: { key: K; dir: Dir },
  key: K,
) {
  return current.key === key
    ? { key, dir: current.dir === "asc" ? ("desc" as const) : ("asc" as const) }
    : { key, dir: "asc" as const };
}
