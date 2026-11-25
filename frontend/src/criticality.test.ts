import { expect, test } from "vitest";
import { criticalityLabel } from "./criticality";

test("names the five asset importance levels", () => {
  expect([1, 2, 3, 4, 5].map(criticalityLabel)).toEqual([
    "매우 낮음",
    "낮음",
    "보통",
    "높음",
    "매우 높음",
  ]);
});

test("shows a dash when there is no value or it is out of range", () => {
  for (const value of [null, undefined, 0, 6, 2.5])
    expect(criticalityLabel(value)).toBe("—");
});
