import { useState } from "react";
import type { GraphView } from "./graph-model";
import type { Point } from "./graph-layout";

export type GraphMemory = Record<GraphView, Map<string, Point>>;

// Node positions live above the graph tab so they survive a trip to another tab; a reload or another incident starts over.
export function useGraphMemory(incidentId: string) {
  const [saved, set] = useState<{ id: string; memory: GraphMemory } | null>(
    null,
  );
  const memory =
    saved?.id === incidentId
      ? saved.memory
      : { ticket: new Map(), entity: new Map() };
  return [
    memory,
    (next: GraphMemory) => set({ id: incidentId, memory: next }),
  ] as const;
}
