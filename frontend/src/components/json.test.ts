import { expect, test } from "vitest";
import sample from "../../../tests/fixtures/frontend/json_viewer.json";
import { flatten } from "./json";

test("flattens nested objects into field rows as plain strings", () => {
  const rows = Object.fromEntries(flatten(sample));
  expect(rows["id"]).toBe("raw_01a19f93-1266-7000-8000-000000000901");
  expect(rows["fetched_at"]).toBe("1793678580000");
  expect(rows["verdict"]).toBe("null");
  expect(rows["tags"]).toBe("T1190, T1059");
  expect(rows["empty_list"]).toBe("[]");
  expect(rows["empty_object"]).toBe("{}");
  expect(rows["entities[1].value"]).toBe("https://example.com/login");
  expect(rows["original.message"]).toBe(sample.original.message);
  expect(rows["original.<b>key</b>"]).toBe("값");
});

test("keeps field order and handles a top-level array or value", () => {
  expect(flatten(sample).map(([key]) => key)[0]).toBe("id");
  expect(flatten([{ id: "T1190", name: null }])).toEqual([
    ["[0].id", "T1190"],
    ["[0].name", "null"],
  ]);
  expect(flatten("text")).toEqual([["value", "text"]]);
});
