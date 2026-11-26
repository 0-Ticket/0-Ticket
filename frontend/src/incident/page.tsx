import { useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { get } from "../api/client";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { useCan } from "../auth/session";
import { Severity, Status } from "../badges";
import { ErrorState } from "../error-state";
import { IncidentGraph } from "../incident-graph";
import { ReviewActions } from "../review-actions";
import { ClassificationBasis } from "./basis";
import { useGraphMemory } from "./graph-memory";
import type { GraphView } from "./graph-model";
import { EntityTable } from "./entity-table";
import { HistoryTab } from "./history-tab";
import { CopyButton } from "./kit";
import { decisionCounts } from "./model";
import { OverviewTab } from "./overview-tab";
import { TicketTable } from "./ticket-table";

const TABS = ["overview", "graph", "tickets", "entities", "history"] as const;
type Tab = (typeof TABS)[number];
const STEPS: [string, string[]][] = [
  ["분석 중", ["analyzing"]],
  ["승인 대기", ["awaiting_review"]],
  ["확정 / 기각", ["confirmed", "dismissed"]],
];

// What the list passes along when it opens an incident: where "목록으로" goes back to, and the ids of that list page.
type FromList = { back?: string; ids?: string[] };

function Neighbour({
  label,
  text,
  to,
  state,
}: {
  label: string;
  text: string;
  to: string | undefined;
  state: FromList | null;
}) {
  return to ? (
    <Link
      to={to}
      state={state}
      aria-label={label}
      className="incident-step-link"
    >
      {text}
    </Link>
  ) : (
    <button
      type="button"
      disabled
      aria-label={label}
      className="incident-step-link"
    >
      {text}
    </button>
  );
}

function Header({
  data,
  from,
  caseId,
  onApproved,
}: {
  data: IncidentDetail;
  from: FromList | null;
  caseId: string | null;
  onApproved: (caseId: string) => void;
}) {
  const can = useCan();
  const { incident } = data;
  const index = from?.ids?.indexOf(incident.id) ?? -1;
  const neighbour = (at: number) =>
    index >= 0 && from?.ids?.[at] ? `/incidents/${from.ids[at]}` : undefined;
  const counts = decisionCounts(data.tickets);
  const step = STEPS.findIndex(([, states]) =>
    states.includes(incident.status),
  );
  return (
    <header className="incident-head">
      <div className="incident-nav">
        <Link to={from?.back ?? "/incidents"}>
          <span aria-hidden="true">← </span>목록으로
        </Link>
        <span className="incident-steps">
          <Neighbour
            label="이전 Incident"
            text="‹ 이전"
            to={neighbour(index - 1)}
            state={from}
          />
          <Neighbour
            label="다음 Incident"
            text="다음 ›"
            to={neighbour(index + 1)}
            state={from}
          />
        </span>
      </div>
      <div className="incident-title-row">
        <div>
          <h1>{incident.title}</h1>
          <div className="incident-meta">
            <code>{incident.id}</code>
            <CopyButton value={incident.id} label="Incident ID" />
            <Status value={incident.status} />
            <Severity value={incident.assessed_severity ?? incident.severity} />
          </div>
        </div>
        <div className="incident-decide">
          <ReviewActions
            id={incident.id}
            status={incident.status}
            onApproved={onApproved}
          />
          {caseId && can("case.read") && (
            <Link to={`/cases?selected=${caseId}`}>Case 보기</Link>
          )}
        </div>
      </div>
      <div role="group" aria-label="요약 숫자" className="incident-numbers">
        <dl>
          {(
            [
              ["Ticket", data.tickets.length],
              ["Alert", data.alerts.length],
              ["엔티티", incident.entities.length],
              ["malicious", counts.malicious],
              ["undetermined", counts.undetermined],
              ["benign", counts.benign],
              ["판정 전", counts.pending],
            ] as [string, number][]
          ).map(([name, value]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <ol className="incident-progress" aria-label="진행 단계">
        {STEPS.map(([name], i) => (
          <li key={name} aria-current={i === step ? "step" : undefined}>
            {name}
          </li>
        ))}
      </ol>
    </header>
  );
}

export function IncidentPage({ id }: { id: string }) {
  const location = useLocation();
  const from = location.state as FromList | null;
  const [search, setSearch] = useSearchParams();
  const [caseId, setCaseId] = useState<string | null>(null);
  const [memory, setMemory] = useGraphMemory(id);
  const query = useQuery({
    queryKey: ["detail", "incidents", id],
    queryFn: ({ signal }) =>
      get<IncidentDetail>(`incidents/${encodeURIComponent(id)}`, signal),
  });
  if (query.isPending) return <p role="status">Incident를 불러오는 중…</p>;
  if (query.error)
    return (
      <ErrorState
        inline
        error={query.error}
        retry={() => void query.refetch()}
      />
    );
  const data = query.data;
  const asked = search.get("tab");
  const tab: Tab = TABS.find((t) => t === asked) ?? "overview";
  const labels: Record<Tab, [string, number | null]> = {
    overview: ["개요", null],
    graph: ["관계 그래프", null],
    tickets: ["Ticket", data.tickets.length],
    entities: ["엔티티", data.incident.entities.length],
    history: ["분석 이력", data.artifacts.length],
  };
  function go(change: (params: URLSearchParams) => void) {
    const params = new URLSearchParams(search);
    change(params);
    // The list state rides along, or previous/next and "목록으로" would be lost on a tab change.
    setSearch(params, { replace: true, state: location.state });
  }
  const open = (next: Tab) =>
    go((params) => {
      if (next === "overview") params.delete("tab");
      else params.set("tab", next);
    });
  // Only the graph's view (ticket or entity) is kept in the address; search words and filters are not.
  const view: GraphView = search.get("view") === "entity" ? "entity" : "ticket";
  const openView = (next: GraphView) =>
    go((params) => {
      if (next === "ticket") params.delete("view");
      else params.set("view", next);
    });
  return (
    <div className="incident-page">
      <Header data={data} from={from} caseId={caseId} onApproved={setCaseId} />
      <div role="tablist" aria-label="Incident 탭" className="incident-tabs">
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => open(t)}
          >
            {labels[t][0]}
            {labels[t][1] !== null && (
              <span className="count">{labels[t][1]}</span>
            )}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="incident-panel">
        {tab === "overview" && (
          <OverviewTab data={data} showTickets={() => open("tickets")} />
        )}
        {tab === "graph" && (
          <>
            <IncidentGraph
              detail={data}
              view={view}
              onView={openView}
              memory={memory}
              onMemory={setMemory}
            />
            <ClassificationBasis
              incident={data.incident}
              ticketGraphs={data.ticket_graphs}
              titles={Object.fromEntries(
                data.tickets.map((t) => [t.id, t.title]),
              )}
            />
          </>
        )}
        {tab === "tickets" &&
          (data.tickets.length ? (
            <TicketTable detail={data} />
          ) : (
            <div className="card empty">
              <h3>연결된 Ticket이 없습니다</h3>
              <p>
                분석이 진행되면 이 Incident와 관련된 Ticket이 여기에 표시됩니다.
              </p>
              <button type="button" onClick={() => void query.refetch()}>
                분석 상태 새로고침
              </button>
            </div>
          ))}
        {tab === "entities" && <EntityTable detail={data} />}
        {tab === "history" && <HistoryTab data={data} />}
      </div>
    </div>
  );
}
