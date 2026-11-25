import { expect, test } from "vitest";
import page from "../../../tests/fixtures/frontend/incident_page.json";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import {
  decisionCounts,
  entityRows,
  paginate,
  searchTickets,
  sortTickets,
} from "./model";

const detail = page as unknown as IncidentDetail;
const tickets = detail.tickets;
const withEntities = {
  ...detail,
  incident: { ...detail.incident, entities: page.entities },
} as IncidentDetail;

test("entity rows count the tickets and alerts that hold the entity and keep the earliest sighting", () => {
  const rows = entityRows(withEntities);
  expect(rows).toHaveLength(5);
  for (const row of rows) {
    expect(
      { tickets: row.tickets, alerts: row.alerts, first: row.first },
      row.key,
    ).toEqual(
      page.expected.entity_rows[
        `${row.type}|${row.value}` as keyof typeof page.expected.entity_rows
      ],
    );
  }
});

test("decision counts put an undecided ticket under pending", () => {
  expect(decisionCounts(tickets)).toEqual(page.expected.decision_counts);
});

test("ticket search matches the title or the id, ignoring case", () => {
  expect(searchTickets(tickets, "sql").map((t) => t.id)).toEqual([
    tickets[0].id,
  ]);
  expect(searchTickets(tickets, "000000000072")).toHaveLength(1);
  expect(searchTickets(tickets, "  ")).toHaveLength(3);
});

test("tickets sort by severity, time, evidence and verdict in both directions", () => {
  const ids = (key: Parameters<typeof sortTickets>[1], dir: "asc" | "desc") =>
    sortTickets(tickets, key, dir).map((t) => t.id.slice(-2));
  expect(ids("severity", "desc")).toEqual(["71", "72", "73"]);
  expect(ids("created_at", "desc")).toEqual(["73", "72", "71"]);
  expect(ids("evidence_count", "asc")).toEqual(["72", "73", "71"]);
  expect(ids("decision", "asc")).toEqual(["71", "72", "73"]); // malicious, undetermined, then none
});

test("paginate slices a page and clamps an out-of-range page", () => {
  const rows = Array.from({ length: 25 }, (_, i) => i);
  expect(paginate(rows, 1, 10)).toEqual({
    rows: rows.slice(0, 10),
    page: 1,
    pages: 3,
  });
  expect(paginate(rows, 9, 10).page).toBe(3);
  expect(paginate([], 1, 10)).toEqual({ rows: [], page: 1, pages: 1 });
});
