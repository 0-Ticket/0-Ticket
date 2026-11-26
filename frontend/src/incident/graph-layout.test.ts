import { expect, test } from "vitest";
import { fit, layout, type Point } from "./graph-layout";

const nodes = ["a", "b", "c", "d"].map((key) => ({ key }));
const edges = [
  { from: "a", to: "b" },
  { from: "b", to: "c" },
  { from: "c", to: "d" },
];

test("places every node at a finite point, the same way each time", () => {
  const one = layout(nodes, edges, new Map());
  const two = layout(nodes, edges, new Map());
  expect([...one.keys()]).toEqual(["a", "b", "c", "d"]);
  for (const p of one.values()) {
    expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
  }
  expect(Object.fromEntries(one)).toEqual(Object.fromEntries(two));
});

test("keeps pinned nodes where they were and places the new one around them", () => {
  const pinned = new Map<string, Point>([
    ["a", { x: 500, y: 40 }],
    ["b", { x: -300, y: 80 }],
  ]);
  const result = layout(nodes, edges, pinned);
  expect(result.get("a")).toEqual({ x: 500, y: 40 });
  expect(result.get("b")).toEqual({ x: -300, y: 80 });
  expect(result.get("c")).toBeDefined();
  expect(result.get("c")).not.toEqual(result.get("d"));
});

test("when every node is pinned nothing is recomputed", () => {
  const pinned = new Map(nodes.map((n, i) => [n.key, { x: i * 10, y: 0 }]));
  expect(Object.fromEntries(layout(nodes, edges, pinned))).toEqual(
    Object.fromEntries(pinned),
  );
});

test("fit shrinks the view to hold far nodes and never enlarges it", () => {
  expect(fit([], 900, 560)).toEqual({ x: 0, y: 0, k: 1 });
  expect(fit([{ x: 0, y: 0 }], 900, 560).k).toBe(1);
  const wide = fit(
    [
      { x: -2000, y: 0 },
      { x: 2000, y: 0 },
    ],
    900,
    560,
  );
  expect(wide.k).toBeLessThan(0.25);
});
