// Dashboard regions only show what a list or metrics response already holds.
// Counts and top items use the first loaded page as received: no sorting, no derived meaning.
export const TOP_ITEMS = 5;

// Groups by the given value in first-appearance order. Display only.
export function countBy<T>(items: T[], value: (item: T) => string): [string, number][] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = value(item);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts];
}
