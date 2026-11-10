export function flatten(value: unknown, path = ""): [string, string][] {
  if (Array.isArray(value)) {
    if (!value.length) return [[path || "value", "[]"]];
    if (value.every((item) => item === null || typeof item !== "object"))
      return [[path || "value", value.map(String).join(", ")]];
    return value.flatMap((item, index) => flatten(item, `${path}[${index}]`));
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return [[path || "value", "{}"]];
    return entries.flatMap(([key, item]) =>
      flatten(item, path ? `${path}.${key}` : key),
    );
  }
  return [[path || "value", String(value)]];
}
