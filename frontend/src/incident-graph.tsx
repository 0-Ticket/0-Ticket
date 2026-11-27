import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";
import type { IncidentDetail } from "./api/generated/IncidentDetail";
import { criticalityLabel } from "./criticality";
import { fit, layout, type Point } from "./incident/graph-layout";
import type { GraphMemory } from "./incident/graph-memory";
import {
  ENTITY_CAP,
  buildGraph,
  facts,
  arrowLinks,
  directNeighbours,
  matches,
  type GNode,
  type GraphView,
} from "./incident/graph-model";

const NODE_W = 168;
const NODE_H = 44;
const VIEW_W = 900; // shortcut: "fit" assumes this viewport size instead of measuring it, measure when the graph gets a resizable panel
const VIEW_H = 560;
const MIN_K = 0.2;
const MAX_K = 3;
const LINKS_SHOWN = 8;
// The lines between entities of one alert can be too dense to read. Set to false to draw only the src → dst arrows
// and show the other lines when a node is chosen (plan 380, "선 밀집").
const PLAIN_LINES_BY_DEFAULT = true;

const KIND: Record<GNode["kind"], string> = {
  incident: "Incident",
  ticket: "Ticket",
  alert: "Alert",
  entity: "Entity",
};
const nodeText = (n: GNode) =>
  n.kind === "entity" ? `${n.type}: ${n.value}` : `${KIND[n.kind]} ${n.label}`;

type Vt = { x: number; y: number; k: number };
type Drag = {
  kind: "pan" | "node";
  x: number;
  y: number;
  key: string;
  from: Point;
  vt: Vt;
  moved: boolean;
};

// Where a line meets the edge of the node it points at, so the arrowhead is not hidden under the node.
function stop(from: Point, to: Point): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const t = Math.min(
    NODE_W / 2 / Math.max(Math.abs(dx), 1e-6),
    NODE_H / 2 / Math.max(Math.abs(dy), 1e-6),
    1,
  );
  return { x: to.x - dx * t, y: to.y - dy * t };
}

export function IncidentGraph({
  detail,
  view,
  onView,
  memory,
  onMemory,
  start,
}: {
  detail: IncidentDetail;
  view: GraphView;
  onView: (view: GraphView) => void;
  memory: GraphMemory;
  onMemory: (memory: GraphMemory) => void;
  // JSON [type, value] of an entity to open chosen (the entity table's "그래프에서 보기"); read once when the graph opens.
  start?: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(() => {
    try {
      const [type, value] = JSON.parse(start ?? "null") as unknown[];
      return typeof type === "string" && typeof value === "string"
        ? JSON.stringify(["entity", type, value])
        : null;
    } catch {
      return null;
    }
  });
  const [hovered, setHovered] = useState<string | null>(null);
  const [vt, setVt] = useState<Vt | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const zoomRef = useRef<(factor: number, px: number, py: number) => void>(
    () => {},
  );

  const graph = useMemo(
    () =>
      buildGraph(detail, view, {
        expanded,
        types,
        query,
        include: selected ?? undefined,
      }),
    [detail, view, expanded, types, query, selected],
  );
  const chosen = graph.nodes.find((n) => n.key === selected) ?? null;
  const shown = graph;
  const pinned = memory[view];
  const placed = useMemo(
    () => layout(shown.nodes, shown.edges, pinned),
    [shown, pinned],
  );
  const current: Vt = vt ?? fit([...placed.values()], VIEW_W, VIEW_H);
  // The graph is drawn once and then only grows (D-083, since the page reads the incident again on a timer): the first
  // picture's node places and view are kept, so nodes that arrive later do not push the others around.
  // "화면에 맞추기" empties `vt`, and this puts the fit for what is shown now back.
  if (!vt && placed.size) setVt(current);
  useEffect(() => remember());

  // Before anything changes what is shown, the places the nodes have now are remembered, so they do not move.
  function remember(extra?: [string, Point]) {
    const next = new Map(pinned);
    let changed = false;
    for (const [key, at] of placed)
      if (!next.has(key)) {
        next.set(key, at);
        changed = true;
      }
    if (extra) {
      next.set(...extra);
      changed = true;
    }
    if (changed) onMemory({ ...memory, [view]: next });
  }
  const change = (apply: () => void) => {
    remember();
    apply();
  };
  const toggle = (set: Set<string>, value: string) => {
    const next = new Set(set);
    if (!next.delete(value)) next.add(value);
    return next;
  };

  function zoom(factor: number, px = 0, py = 0) {
    const k = Math.min(MAX_K, Math.max(MIN_K, current.k * factor));
    const r = k / current.k;
    setVt({ k, x: px - (px - current.x) * r, y: py - (py - current.y) * r });
  }
  useEffect(() => {
    zoomRef.current = zoom;
  });
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    // Only Ctrl/⌘ + wheel zooms, so a plain wheel keeps scrolling the page. React's onWheel is passive, hence the native listener.
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const box = el.getBoundingClientRect();
      zoomRef.current(
        e.deltaY < 0 ? 1.15 : 1 / 1.15,
        e.clientX - box.left - box.width / 2,
        e.clientY - box.top - box.height / 2,
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    const target = e.target as HTMLElement;
    if (e.button !== 0 || target.closest("button, input")) return;
    suppressClick.current = false;
    const el = target.closest<HTMLElement>("[data-node]");
    const key = el?.dataset.node ?? "";
    remember();
    drag.current = {
      kind: el ? "node" : "pan",
      x: e.clientX,
      y: e.clientY,
      key,
      from: placed.get(key) ?? { x: 0, y: 0 },
      vt: current,
      moved: false,
    };
    setVt(current);
    // Capture on the node itself, or the click that follows a press without moving would land on the viewport.
    (el ?? e.currentTarget).setPointerCapture?.(e.pointerId);
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 3) return;
    d.moved = true;
    suppressClick.current = true;
    if (d.kind === "pan") setVt({ ...d.vt, x: d.vt.x + dx, y: d.vt.y + dy });
    else
      remember([
        d.key,
        { x: d.from.x + dx / d.vt.k, y: d.from.y + dy / d.vt.k },
      ]);
  }

  const lit = (n: GNode) => !query.trim() || matches(n, query);
  const litKeys = new Set(shown.nodes.filter(lit).map((n) => n.key));
  const entityView = view === "entity";
  const arrowsOnly = entityView && !chosen && !PLAIN_LINES_BY_DEFAULT;
  const lines = shown.edges.filter((e) => !arrowsOnly || e.arrow);
  // What the pointer is on wins over the choice; everything outside it stays on screen and is only faded.
  const focus = hovered ?? chosen?.key ?? null;
  const near = focus ? directNeighbours(shown, focus) : null;
  const incidentNode: GNode = {
    key: "",
    kind: "incident",
    id: detail.incident.id,
    label: detail.incident.title || detail.incident.id,
  };
  const info = chosen ?? incidentNode;
  const ticket =
    info.kind === "ticket"
      ? detail.tickets.find((t) => t.id === info.id)
      : undefined;
  const importance =
    info.kind === "entity"
      ? detail.entity_criticality.find(
          (c) => c.type === info.type && c.value === info.value,
        )?.criticality
      : null;
  const links =
    chosen?.kind === "entity" ? arrowLinks(detail, chosen.key) : null;
  const select = (key: string | null) => change(() => setSelected(key));

  return (
    <section className="incident-graph">
      <div className="incident-graph-toolbar">
        <div
          className="incident-graph-modes"
          role="group"
          aria-label="그래프 보기"
        >
          {(["ticket", "entity"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => {
                if (view === v) return;
                remember();
                setSelected(null);
                setTypes(new Set());
                setVt(null);
                onView(v);
              }}
            >
              {v === "ticket" ? "Ticket" : "Entity"}
            </button>
          ))}
        </div>
        <input
          type="text"
          aria-label="노드 검색"
          placeholder="노드 검색"
          value={query}
          onChange={(e) => change(() => setQuery(e.target.value))}
        />
        <div
          className="incident-graph-chips"
          role="group"
          aria-label="종류 필터"
        >
          {graph.types.map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={types.has(t)}
              onClick={() => change(() => setTypes(toggle(types, t)))}
            >
              {t}
            </button>
          ))}
        </div>
        <div
          className="incident-graph-zoom"
          role="group"
          aria-label="확대·이동"
        >
          <button type="button" onClick={() => zoom(1.25)}>
            확대
          </button>
          <button type="button" onClick={() => zoom(1 / 1.25)}>
            축소
          </button>
          <button type="button" onClick={() => setVt(null)}>
            화면에 맞추기
          </button>
        </div>
      </div>
      <div className="incident-graph-legend" aria-label="범례">
        {entityView ? (
          <>
            <span className="plain">
              같은 Alert에 함께 나온 엔티티끼리 이어집니다
            </span>
            <span className="arrow">
              화살표는 Alert에 기록된 출발→목적지 방향이며 공격 순서가 아님
            </span>
            {arrowsOnly && <span>나머지 연결은 노드를 선택하면 보입니다</span>}
          </>
        ) : (
          <span className="plain">
            Incident 소속과 Ticket(펼치면 Alert)에 붙은 엔티티를 잇습니다. 공격
            순서나 최종 선택 이유를 뜻하지 않습니다.
          </span>
        )}
      </div>
      {entityView && graph.hidden > 0 && (
        <p className="incident-graph-note">
          연결 수 상위 {ENTITY_CAP}개만 표시합니다 (전체 {graph.total}개 중{" "}
          {graph.nodes.length}개). 나머지는 종류 필터와 검색으로 꺼낼 수
          있습니다.
        </p>
      )}
      <div className="incident-graph-body">
        <div
          ref={viewport}
          className="incident-graph-viewport"
          role="region"
          aria-label="Incident 관계도"
          tabIndex={0}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={() => (drag.current = null)}
          onPointerCancel={() => (drag.current = null)}
          onKeyDown={(e) => {
            if (e.key === "Escape" && chosen) select(null);
          }}
        >
          <div
            className="incident-graph-world"
            style={{
              transform: `translate(${current.x}px, ${current.y}px) scale(${current.k})`,
            }}
          >
            <svg className="incident-graph-lines" aria-hidden="true">
              <defs>
                <marker
                  id="incident-graph-arrowhead"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M0 0 L10 5 L0 10 z" />
                </marker>
              </defs>
              {lines.map((e) => {
                const a = placed.get(e.from)!;
                const b = placed.get(e.to)!;
                const end = e.arrow ? stop(a, b) : b;
                const dim = !litKeys.has(e.from) || !litKeys.has(e.to);
                const fade =
                  focus !== null && e.from !== focus && e.to !== focus;
                return (
                  <line
                    key={e.key}
                    data-arrow={e.arrow}
                    className={
                      [dim ? "dim" : "", fade ? "faded" : ""]
                        .join(" ")
                        .trim() || undefined
                    }
                    x1={a.x}
                    y1={a.y}
                    x2={end.x}
                    y2={end.y}
                    markerEnd={
                      e.arrow ? "url(#incident-graph-arrowhead)" : undefined
                    }
                  />
                );
              })}
            </svg>
            {shown.nodes.map((n) => {
              const at = placed.get(n.key)!;
              const alerts =
                n.kind === "ticket"
                  ? (detail.tickets.find((t) => t.id === n.id)?.alert_ids
                      .length ?? 0)
                  : 0;
              const open = expanded.has(n.id);
              return (
                <div
                  key={n.key}
                  data-node={n.key}
                  className={[
                    "incident-graph-node",
                    n.kind,
                    n.key === chosen?.key ? "selected" : "",
                    lit(n) ? "" : "dim",
                    near && !near.has(n.key) ? "faded" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  style={{ left: at.x - NODE_W / 2, top: at.y - NODE_H / 2 }}
                  role="group"
                  tabIndex={0}
                  aria-label={nodeText(n)}
                  aria-current={n.key === chosen?.key ? "true" : undefined}
                  onMouseEnter={() => setHovered(n.key)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => {
                    if (suppressClick.current) suppressClick.current = false;
                    else select(n.key);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      select(n.key);
                    }
                  }}
                >
                  <i className="marker" aria-hidden="true" />
                  <strong>{n.kind === "entity" ? n.type : KIND[n.kind]}</strong>
                  <span>{n.label}</span>
                  {alerts > 0 && (
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-label={`Alert ${open ? "접기" : "펼치기"}: ${n.label}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        change(() => setExpanded(toggle(expanded, n.id)));
                      }}
                    >
                      {open ? "−" : "+"}
                      {alerts}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <aside className="incident-graph-inspector" aria-label="선택된 노드">
          <span className="eyebrow">
            {chosen
              ? `선택된 노드 · ${KIND[info.kind].toUpperCase()}`
              : "Incident 요약"}
          </span>
          <h4>{info.label}</h4>
          {ticket?.decision ? (
            <span className="badge decision">{ticket.decision}</span>
          ) : null}
          <code>{info.kind === "entity" ? info.type : info.id}</code>
          <dl>
            {facts(detail, info).map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{value}</dd>
              </div>
            ))}
            {importance != null ? (
              <div>
                <dt>자산 중요도</dt>
                <dd>{criticalityLabel(importance)}</dd>
              </div>
            ) : null}
          </dl>
          {chosen && (
            <button type="button" onClick={() => select(null)}>
              선택 해제
            </button>
          )}
          {links && (links.from.length > 0 || links.to.length > 0) && (
            <ul aria-label="이 노드의 연결" className="incident-graph-links">
              {links.from.slice(0, LINKS_SHOWN).map((n) => (
                <li key={n.key}>{`${n.type}: ${n.value} → 이 노드`}</li>
              ))}
              {links.to.slice(0, LINKS_SHOWN).map((n) => (
                <li key={n.key}>{`이 노드 → ${n.type}: ${n.value}`}</li>
              ))}
            </ul>
          )}
          {chosen && (
            <small>
              이 노드와 직접 연결된 노드·선만 진하게 보입니다. 나머지는 흐리게
              남아 있습니다.
            </small>
          )}
        </aside>
      </div>
      <p className="incident-graph-hint">
        Ctrl(⌘)+휠로 확대·축소하고, 배경을 끌어 이동하고, 노드를 끌어 옮길 수
        있습니다. 노드는 Tab으로 고르고 Enter로 선택하며 Esc로 선택을
        해제합니다.
      </p>
    </section>
  );
}
