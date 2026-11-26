import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

export type Point = { x: number; y: number };
type Body = SimulationNodeDatum & { key: string };

// Places nodes with d3-force (D-079). Nodes already in `pinned` keep their place; only new ones move.
// shortcut: runs a fixed number of ticks on the render path, fine for the ~100 nodes an incident has, move it to a worker above a few hundred.
export function layout(
  nodes: { key: string }[],
  edges: { from: string; to: string }[],
  pinned: Map<string, Point>,
): Map<string, Point> {
  const out = new Map<string, Point>();
  if (nodes.every((n) => pinned.has(n.key))) {
    for (const n of nodes) out.set(n.key, pinned.get(n.key)!);
    return out;
  }
  const bodies: Body[] = nodes.map((n) => {
    const at = pinned.get(n.key);
    return at
      ? { key: n.key, x: at.x, y: at.y, fx: at.x, fy: at.y }
      : { key: n.key };
  });
  const links: SimulationLinkDatum<Body>[] = edges.map((e) => ({
    source: e.from,
    target: e.to,
  }));
  const sim = forceSimulation(bodies)
    .force(
      "link",
      forceLink<Body, SimulationLinkDatum<Body>>(links)
        .id((b) => b.key)
        .distance(150),
    )
    .force("charge", forceManyBody().strength(-420))
    .force("collide", forceCollide(96))
    .force("x", forceX(0).strength(0.04))
    .force("y", forceY(0).strength(0.04))
    .stop();
  sim.tick(300);
  for (const b of bodies) out.set(b.key, { x: b.x ?? 0, y: b.y ?? 0 });
  return out;
}

// Where to put the view so that every placed node is on screen.
export function fit(points: Point[], width: number, height: number) {
  if (!points.length) return { x: 0, y: 0, k: 1 };
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const [x0, x1] = [Math.min(...xs) - 110, Math.max(...xs) + 110];
  const [y0, y1] = [Math.min(...ys) - 50, Math.max(...ys) + 50];
  const k = Math.min(1, width / (x1 - x0), height / (y1 - y0));
  return { x: (-(x0 + x1) / 2) * k, y: (-(y0 + y1) / 2) * k, k };
}
