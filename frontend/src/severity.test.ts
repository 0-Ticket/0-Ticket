import { expect, test } from "vitest";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import seed from "../../tests/fixtures/api/ui_seed.json";
import sample from "../../tests/fixtures/frontend/severity_labels.json";
import { dashboard, server, show } from "./test-utils";
import { severityLabel } from "./severity";

const { labels, outside } = sample;
const reversed = [...labels].reverse();

test("severity_id 0-6 map to the labels of D-074", () => {
  expect(labels.map((_, level) => severityLabel(level))).toEqual(labels);
});

test("null shows a dash and values outside 0-6 fall back to unknown", () => {
  expect(severityLabel(null)).toBe("—");
  for (const value of outside) expect(severityLabel(value)).toBe(labels[0]);
});

test("the Ticket list shows every label in the badge and in the filter", async () => {
  dashboard();
  server.use(
    http.get("*/api/tickets", () =>
      HttpResponse.json({
        items: labels.map((_, level) => ({
          ...seed.tickets[level],
          severity: level,
          seed_source: "dev-seed-ui",
          incident: null,
        })),
        next_cursor: null,
      }),
    ),
  );
  show("/tickets");
  const table = await screen.findByRole("table");
  expect(
    within(table).getByRole("columnheader", { name: "심각도" }),
  ).toBeInTheDocument();
  const badges = within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => row.querySelector(".badge.severity")?.textContent);
  expect(badges).toEqual(labels);
  const chips = within(
    screen.getByRole("group", { name: "심각도 필터" }),
  ).getAllByRole("button");
  expect(chips.map((chip) => chip.textContent)).toEqual(reversed);
});

test("the dashboard shows the labels in the bars and the Top 10", async () => {
  dashboard(undefined, [
    { ...seed.incidents[0], assessed_severity: 6, display_severity: 6 },
    { ...seed.incidents[1], assessed_severity: 3, display_severity: 3 },
  ]);
  show("/");
  const bars = await screen.findByLabelText("Ticket 심각도 분포");
  const rows = [...bars.querySelectorAll(".risk-row > span:first-child")];
  expect(rows.map((row) => row.textContent)).toEqual(reversed);
  expect(
    screen.getByRole("heading", { name: "심각도별 Ticket" }),
  ).toBeInTheDocument();
  const top = screen
    .getByRole("heading", { name: "Incident 심각도 Top 10" })
    .closest("article")!;
  expect(within(top).getByText("심각도")).toBeInTheDocument();
  const listed = [...top.querySelectorAll(".small-list .badge.severity")];
  expect(listed.map((badge) => badge.textContent)).toEqual([
    labels[6],
    labels[3],
  ]);
});
