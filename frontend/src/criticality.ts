// Asset importance (1-5, 5 is most important) shown on screen. Every importance text comes from here.
const names = ["매우 낮음", "낮음", "보통", "높음", "매우 높음"];

export function criticalityLabel(value: number | null | undefined): string {
  return (Number.isInteger(value) && names[(value as number) - 1]) || "—";
}
