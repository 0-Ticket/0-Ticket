import { useEffect, useRef } from "react";
import {
  Link,
  Navigate,
  NavLink,
  useLocation,
  useSearchParams,
} from "react-router";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { Icon, type IconName } from "./components/icons";
import { JsonViewer } from "./components/json-viewer";
import { FilterChips } from "./components/filter-chips";
import logo from "./assets/o-ticket-mark.png";
import { Button } from "./components/ui/button";
import { get, itemId, itemTitle, itemStatus, itemSeverity } from "./api/client";
import type { Resource, Page, Item, Detail } from "./api/client";
import { usePager } from "./pager";
import { ErrorState } from "./error-state";
import type { Dashboard } from "./api/generated/Dashboard";
import type { Me } from "./api/generated/Me";
import {
  ForcedPasswordPage,
  LoginPage,
  SettingsPage,
  SignupPage,
} from "./auth/pages";
import { useLoginTarget, useLogout, useMe } from "./auth/session";
import { UsersPage } from "./users/users-page";

const menu: [string, string, IconName, string[]][] = [
  ["/", "DashBoard", "dashboard", ["dashboard.read"]],
  ["/alerts", "Alert/Event", "alerts", ["alert.read", "event.read"]],
  ["/tickets", "Ticket", "tickets", ["ticket.read"]],
  ["/incidents", "Incident", "incidents", ["incident.read"]],
  ["/cases", "Case", "cases", ["case.read"]],
  ["/hunts", "Hunting", "hunts", ["hunt.read"]],
];
const adminMenu: [string, string, string][] = [
  ["/policy", "Ticket 정책", "policy.read"],
  ["/users", "사용자 관리", "user.read"],
];
const titles: Record<Resource, string> = {
  alerts: "Alert / Event",
  events: "Alert / Event",
  tickets: "Ticket",
  incidents: "Incident",
  cases: "Case",
  hunts: "Hunting",
};
const statusNames: Record<string, string> = {
  pending: "대기",
  succeeded: "성공",
  failed: "실패",
  new: "L1 대기",
  held: "보류",
  closed: "종결",
  escalated: "L2 대기",
  linked: "Incident 연결",
  analyzing: "분석 중",
  awaiting_review: "승인 대기",
  confirmed: "승인 / 확인됨",
  human_handling: "사람 처리",
  dismissed: "위협 아님",
  open: "열림",
  in_progress: "처리 중",
  resolved: "해결됨",
  rejected: "기각",
  inconclusive: "판단 유보",
};
const states: Record<Resource, string[]> = {
  alerts: ["pending", "succeeded", "failed"],
  events: ["pending", "succeeded", "failed"],
  tickets: ["new", "held", "closed", "escalated", "linked"],
  incidents: [
    "analyzing",
    "held",
    "awaiting_review",
    "confirmed",
    "human_handling",
    "dismissed",
  ],
  cases: ["open", "in_progress", "resolved"],
  hunts: ["pending", "confirmed", "rejected", "inconclusive", "failed"],
};
const colors = [
  "#cccccc",
  "#447ee3",
  "#447ee3",
  "#ffbf00",
  "#ffbf00",
  "#cf0000",
  "#cf0000",
];
const chartColors = ["#447ee3", "#44aff2", "#2ba68f", "#56b364", "#d9d9d9"];
const severityNames = [
  "미상",
  "1 Level",
  "2 Level",
  "3 Level",
  "4 Level",
  "5 Level",
  "6 Level",
];
function Severity({ value }: { value: number | null }) {
  return value === null ? (
    <span>—</span>
  ) : (
    <span className={`badge severity s${value}`}>{severityNames[value]}</span>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`badge status-${value}`}>
      {statusNames[value] ?? value}
    </span>
  );
}
function Bars({
  counts,
  risk = false,
  horizontal = false,
}: {
  counts: Record<string, number>;
  risk?: boolean;
  horizontal?: boolean;
}) {
  const data = Object.entries(counts)
    .filter(([key]) => !risk || key !== "0")
    .map(([key, value]) => ({
      name: risk ? severityNames[Number(key)] : (statusNames[key] ?? key),
      value,
      key,
    }));
  if (risk) data.reverse();
  if (data.every((d) => d.value === 0))
    return <p className="empty">데이터 없음</p>;
  return (
    <>
      <div aria-hidden="true">
        <ResponsiveContainer
          width="100%"
          height={210}
          initialDimension={{ width: 600, height: 210 }}
        >
          <BarChart
            data={data}
            layout={horizontal ? "vertical" : "horizontal"}
            margin={{
              left: horizontal ? 12 : -20,
              right: 10,
              top: 12,
              bottom: 4,
            }}
          >
            <XAxis
              type={horizontal ? "number" : "category"}
              dataKey={horizontal ? undefined : "name"}
              allowDecimals={false}
              tick={{ fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type={horizontal ? "category" : "number"}
              dataKey={horizontal ? "name" : undefined}
              width={horizontal ? 94 : 60}
              allowDecimals={false}
              tick={{ fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip />
            <Bar
              isAnimationActive={false}
              dataKey="value"
              name="건수"
              radius={horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0]}
              maxBarSize={40}
            >
              {data.map((d, index) => (
                <Cell
                  key={d.key}
                  fill={
                    risk
                      ? colors[Number(d.key)]
                      : chartColors[index % chartColors.length]
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}
function Normalization({
  name,
  counts,
}: {
  name: string;
  counts: Dashboard["normalization"][string];
}) {
  const data = [
    { name: "성공", value: counts.succeeded, color: "#447ee3" },
    { name: "실패", value: counts.failed, color: "#cf0000" },
    { name: "대기", value: counts.pending, color: "#cccccc" },
  ];
  const total = counts.succeeded + counts.failed + counts.pending;
  return (
    <article className="card normalization-card">
      <h3>{name} 정규화 현황</h3>
      <div className="donut">
        <div aria-hidden="true">
          <ResponsiveContainer
            width="100%"
            height={140}
            initialDimension={{ width: 250, height: 140 }}
          >
            <PieChart>
              <Pie
                isAnimationActive={false}
                data={
                  total
                    ? data
                    : [{ name: "데이터 없음", value: 1, color: "#edf1f6" }]
                }
                dataKey="value"
                innerRadius={45}
                outerRadius={62}
                startAngle={90}
                endAngle={450}
                stroke="none"
              >
                {(total
                  ? data
                  : [{ name: "데이터 없음", color: "#edf1f6" }]
                ).map((d) => (
                  <Cell key={d.name} fill={d.color} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div className="donut-total">
          <span>전체</span>
          <strong>{total}건</strong>
        </div>
      </div>
      <div className="normalization-counts">
        {data.map((d) => (
          <div key={d.name}>
            <span>{d.name}</span>
            <strong style={{ color: d.color }}>{d.value}건</strong>
          </div>
        ))}
      </div>
    </article>
  );
}
function SmallList({ items }: { items: Dashboard["top_incidents"] }) {
  return items.length ? (
    <div className="small-list">
      {items.map((item) => (
        <Link key={item.id} to={`/incidents?selected=${item.id}`}>
          <span>
            {item.title}
            <small>{statusNames[item.status]}</small>
          </span>
          <Severity value={item.display_severity} />
        </Link>
      ))}
    </div>
  ) : (
    <p className="empty">데이터 없음</p>
  );
}
function RiskBars({ counts }: { counts: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(counts));
  return (
    <div className="risk-bars" aria-label="Ticket 위험도 분포">
      {[6, 5, 4, 3, 2, 1, 0].map((level) => (
        <div className="risk-row" key={level}>
          <span>{severityNames[level]}</span>
          <div className="risk-track">
            <span
              style={{
                width: `${((counts[level] ?? 0) / max) * 100}%`,
                background: colors[level],
              }}
            />
          </div>
          <span>{counts[level] ?? 0}</span>
        </div>
      ))}
    </div>
  );
}
function DashboardView({ data }: { data: Dashboard }) {
  const steps: [string, number][] = [
    ["정규화 대기 중인\nAlert/Event", data.flow.normalization_pending],
    ["Ticket 승격을 위해\n대기 중인 Alert", data.flow.l1_alerts_pending],
    ["L2 승격을 위해\n대기 중인 Ticket", data.flow.l1_tickets_pending],
    [
      "Incident으로 묶이기\n위해 대기 중인 Ticket",
      data.ticket_status.escalated,
    ],
    ["생성된\nIncident", data.flow.incidents],
    ["승인된\nCase", data.flow.cases],
  ];
  return (
    <>
      <ol className="flow-grid" aria-label="처리 흐름">
        {steps.map(([label, count]) => (
          <li className="kpi" key={label}>
            <span>{label}</span>
            <strong>{(count ?? 0).toLocaleString()}</strong>
          </li>
        ))}
      </ol>
      <div className="dashboard-grid">
        <div className="dashboard-stack">
          <article className="card">
            <div className="card-heading">
              <h3>Tickets by Risk Level</h3>
              <Link to="/tickets">전체 보기 →</Link>
            </div>
            <p className="chart-caption">전체 {data.flow.tickets}건</p>
            <RiskBars counts={data.ticket_severity} />
          </article>
          <article className="card hunting-card">
            <div className="card-heading">
              <h3>Threat Hunting</h3>
              <Link to="/hunts">헌팅 결과 보기 →</Link>
            </div>
            <div className="hunting-metrics">
              <div>
                <span>가설 검증</span>
                <strong>
                  {data.hunting.total}
                  <small>건</small>
                </strong>
              </div>
              <div>
                <span>Ticket 승격</span>
                <strong>
                  {data.hunting.promoted}
                  <small>건</small>
                </strong>
              </div>
            </div>
            <p className="chart-caption">
              전체 가설 대비 승격{" "}
              {data.hunting.promotion_ratio === null
                ? "데이터 없음"
                : `${Math.round(data.hunting.promotion_ratio * 100)}%`}
            </p>
            <div className="progress">
              <span
                style={{
                  width: `${(data.hunting.promotion_ratio ?? 0) * 100}%`,
                }}
              />
            </div>
          </article>
        </div>
        <article className="card top-incidents">
          <div className="card-heading">
            <h3>Incident Risk Top 10</h3>
            <Link to="/incidents">전체 보기 →</Link>
          </div>
          <div className="small-list-heading">
            <span>Incident 정보</span>
            <span>위험도</span>
          </div>
          <SmallList items={data.top_incidents} />
        </article>
      </div>
    </>
  );
}
function Overview({ resource, data }: { resource: Resource; data: Dashboard }) {
  if (resource === "alerts" || resource === "events")
    return (
      <div className="two-col">
        <Normalization name="Alert" counts={data.normalization.alert} />
        <Normalization name="Event" counts={data.normalization.event} />
      </div>
    );
  if (resource === "tickets")
    return (
      <article className="card">
        <h3>위험도별 Ticket</h3>
        <Bars counts={data.ticket_severity} risk />
      </article>
    );
  if (resource === "incidents")
    return (
      <article className="card">
        <h3>Incident 상태 · 전체 {data.flow.incidents}건</h3>
        <Bars counts={data.incident_status} />
      </article>
    );
  if (resource === "hunts")
    return (
      <article className="card">
        <h3>
          전체 가설 {data.hunting.total}건 / Ticket 승격 {data.hunting.promoted}
          건
        </h3>
        <Bars counts={data.hunting.statuses} />
      </article>
    );
  return null;
}
function internalLink(id: string, resource: Resource, label: string) {
  if (
    !/^(alt|evt|raw|tkt|inc|hnt)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      id,
    )
  )
    return null;
  return (
    <Button key={id} variant="outline" size="sm" asChild>
      <Link to={`/${resource}?selected=${id}`}>{label}</Link>
    </Button>
  );
}
function DetailBody({ data }: { data: Detail }) {
  return (
    <>
      {"ticket" in data && (
        <>
          <Severity value={data.severity} />
          <div className="links">
            {data.ticket.alert_ids.map((id, i) =>
              internalLink(id, "alerts", `원본 Alert ${i + 1}`),
            )}
            {data.ticket.hunt_id &&
              internalLink(data.ticket.hunt_id, "hunts", "원본 Hunt")}
          </div>
          <h3>Ticket 판정과 근거</h3>
          <JsonViewer value={data.ticket} />
        </>
      )}
      {"incident" in data && (
        <>
          <div className="links">
            {data.incident.ticket_ids.map((id, i) =>
              internalLink(id, "tickets", `원본 Ticket ${i + 1}`),
            )}
          </div>
          <h3>Incident</h3>
          <JsonViewer value={data.incident} />
          <h3>라운드별 분석 보고서</h3>
          {data.artifacts.length ? (
            data.artifacts.map((a) => (
              <section key={a.id}>
                <h4>분석 라운드 {a.analysis_round}</h4>
                <JsonViewer value={a} />
                {data.proposals
                  .filter((p) => p.artifact_id === a.id)
                  .map((p) => (
                    <div className="proposal" key={p.id}>
                      <strong>
                        {p.kind === "response_action"
                          ? "대응 방안 제안"
                          : "탐지 룰 제안"}
                      </strong>
                      <pre>{p.body}</pre>
                    </div>
                  ))}
              </section>
            ))
          ) : (
            <p>분석 보고서가 없습니다.</p>
          )}
          <div className="review-actions">
            <p>승인·반려 기능은 아직 제공하지 않습니다.</p>
            <Button disabled>승인</Button>
            <Button disabled variant="outline">
              반려
            </Button>
          </div>
        </>
      )}
      {"case" in data && (
        <>
          <div className="links">
            {internalLink(data.case.incident_id, "incidents", "원본 Incident")}
          </div>
          <h3>승인된 Case</h3>
          <JsonViewer value={data.case} />
        </>
      )}
      {"raw_record" in data && (
        <>
          <Status value={data.normalize_status} />
          {data.error_code && <p>실패 코드: {data.error_code}</p>}
          <h3>{data.record ? "정규화 결과 · OCSF" : "정규화 결과 없음"}</h3>
          {data.record && <JsonViewer value={data.record} />}
          <h3>수집 원본</h3>
          <JsonViewer value={data.raw_record} />
        </>
      )}
      {"hunt" in data && (
        <>
          <div className="links">
            {data.ticket_id &&
              internalLink(data.ticket_id, "tickets", "승격 Ticket")}
          </div>
          <h3>가설과 검증 결과</h3>
          <JsonViewer value={data.hunt} />
          <h3>검증 과정 · 실행 요약</h3>
          {data.runs.length ? (
            data.runs.map((r) => (
              <div key={r.run_id} className="proposal">
                <strong>
                  {r.task ?? "실행"} · {r.outcome}
                </strong>
                <JsonViewer value={r} />
              </div>
            ))
          ) : (
            <p>실행 기록이 없습니다.</p>
          )}
          <h3>ATT&amp;CK 기법</h3>
          <JsonViewer value={data.techniques} />
        </>
      )}
    </>
  );
}
function DetailPanel({
  resource,
  id,
  onClose,
}: {
  resource: Resource;
  id: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const query = useQuery({
    queryKey: ["detail", resource, id],
    queryFn: ({ signal }) =>
      get<Detail>(`${resource}/${encodeURIComponent(id)}`, signal),
  });
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="detail-panel"
      aria-labelledby="detail-title"
      onCancel={onClose}
    >
      <header>
        <div>
          <span className="eyebrow">RECORD DETAIL</span>
          <h2 id="detail-title">
            {resource === "alerts"
              ? "Alert"
              : resource === "events"
                ? "Event"
                : titles[resource]}{" "}
            상세
          </h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="상세 닫기">
          ✕
        </Button>
      </header>
      <div className="detail-content">
        {query.isPending ? (
          <p role="status">불러오는 중…</p>
        ) : query.error ? (
          <ErrorState error={query.error} retry={() => void query.refetch()} />
        ) : (
          <DetailBody data={query.data} />
        )}
      </div>
    </dialog>
  );
}
const PAGE_SIZE = 25;
// The list API has no total; derive it from dashboard counts. Origin/severity filters have no count.
function totalCount(
  resource: Resource,
  status: string,
  filtered: boolean,
  d?: Dashboard,
) {
  if (!d || filtered) return undefined;
  const raw = (n: Dashboard["normalization"][string]) => ({
    pending: n.pending,
    succeeded: n.succeeded,
    failed: n.failed,
  });
  const by: Record<string, number> =
    resource === "alerts"
      ? raw(d.normalization.alert)
      : resource === "events"
        ? raw(d.normalization.event)
        : resource === "tickets"
          ? d.ticket_status
          : resource === "incidents"
            ? d.incident_status
            : resource === "cases"
              ? d.case_status
              : d.hunting.statuses;
  return status
    ? (by[status] ?? 0)
    : Object.values(by).reduce((a, b) => a + b, 0);
}
function ListView({
  resource,
  waiting = false,
  summary,
}: {
  resource: Resource;
  waiting?: boolean;
  summary?: Dashboard;
}) {
  const [search, setSearch] = useSearchParams();
  const status = waiting ? "awaiting_review" : (search.get("status") ?? "");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  for (const key of ["cursor", "origin", "severity"])
    if (search.get(key) && (resource === "tickets" || key === "cursor"))
      params.set(key, search.get(key)!);
  if (status) params.set("status", status);
  const path = `${resource}?${params}`;
  const query = useQuery({
    queryKey: ["list", path],
    queryFn: ({ signal }) => get<Page>(path, signal),
  });
  const { current, page } = usePager(query.data?.next_cursor);
  function change(key: string, value: string) {
    const next = new URLSearchParams(search);
    next.delete("cursor");
    next.delete("trail");
    next.delete("selected");
    if (value) next.set(key, value);
    else next.delete(key);
    setSearch(next);
  }
  function select(item: Item) {
    const next = new URLSearchParams(search);
    next.set("selected", itemId(item));
    setSearch(next);
  }
  const selected = search.get("selected");
  const total = totalCount(
    resource,
    status,
    resource === "tickets" &&
      !!(search.get("severity") || search.get("origin")),
    summary,
  );
  // An old cursor link can start past the last page; never show N greater than the maximum.
  const last =
    total === undefined
      ? "-"
      : Math.max(Math.ceil(total / PAGE_SIZE), 1, current);
  return (
    <section className="card list-card">
      <div className="list-toolbar">
        <h3>
          {waiting
            ? "승인 대기 Incident"
            : resource === "alerts"
              ? "Alert"
              : resource === "events"
                ? "Event"
                : titles[resource]}{" "}
          목록
        </h3>
        <div className="filters">
          {!waiting && (
            <FilterChips
              label={
                resource === "alerts" || resource === "events"
                  ? "정규화 상태"
                  : "처리 상태"
              }
              name="상태 필터"
              value={status}
              options={states[resource].map((s) => [s, statusNames[s]])}
              onChange={(v) => change("status", v)}
            />
          )}
          {resource === "tickets" && (
            <>
              <FilterChips
                label="위험도"
                name="위험도 필터"
                value={search.get("severity") ?? ""}
                options={[6, 5, 4, 3, 2, 1, 0].map((i) => [
                  String(i),
                  severityNames[i],
                ])}
                onChange={(v) => change("severity", v)}
              />
              <FilterChips
                label="출처"
                name="출처 필터"
                value={search.get("origin") ?? ""}
                options={["auto", "scenario", "l1", "l3"].map((v) => [v, v])}
                onChange={(v) => change("origin", v)}
              />
            </>
          )}
        </div>
      </div>
      {query.isPending ? (
        <p role="status" className="empty">
          불러오는 중…
        </p>
      ) : query.error ? (
        <ErrorState error={query.error} retry={() => void query.refetch()} />
      ) : query.data.items.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>제목 / ID</th>
                  <th>상태</th>
                  <th>위험도</th>
                  <th>시각</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((item) => (
                  <tr key={itemId(item)} onClick={() => select(item)}>
                    <td>
                      <button className="record-link">{itemTitle(item)}</button>
                      {"origin" in item && (
                        <span className="origin-label">{item.origin}</span>
                      )}
                      <small className="record-id">{itemId(item)}</small>
                    </td>
                    <td>
                      <Status value={itemStatus(item)} />
                    </td>
                    <td>
                      <Severity value={itemSeverity(item)} />
                    </td>
                    <td className="date">
                      {new Date(
                        "fetched_at" in item
                          ? item.fetched_at
                          : "confirmed_at" in item
                            ? item.confirmed_at
                            : item.updated_at,
                      ).toLocaleString("ko-KR")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="empty">조건에 맞는 데이터가 없습니다.</p>
      )}
      <footer className="pagination">
        <div className="pagination-controls">
          <button
            aria-label="이전 페이지"
            disabled={!search.has("cursor") || query.isFetching}
            onClick={() => page("previous")}
          >
            <Icon name="left" />
          </button>
          <span aria-live="polite">
            {current}/{last}
          </span>
          <button
            aria-label="다음 페이지"
            disabled={
              !query.data?.next_cursor || query.isFetching || !!query.error
            }
            onClick={() => page("next")}
          >
            <Icon name="right" />
          </button>
        </div>
      </footer>
      {selected && (
        <DetailPanel
          key={`${resource}/${selected}`}
          resource={resource}
          id={selected}
          onClose={() => {
            const next = new URLSearchParams(search);
            next.delete("selected");
            setSearch(next);
          }}
        />
      )}
    </section>
  );
}
function Workspace({ me }: { me: Me }) {
  const location = useLocation();
  const logout = useLogout();
  const [search] = useSearchParams();
  const slug = location.pathname.slice(1);
  const resource = (
    Object.hasOwn(titles, slug) ? slug : null
  ) as Resource | null;
  const isHome = location.pathname === "/";
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => get<Dashboard>("dashboard", signal),
    enabled: isHome || resource !== null,
  });
  const can = (names: string[]) =>
    names.some((n) => me.permissions.includes(n));
  const page =
    location.pathname === "/settings"
      ? "settings"
      : location.pathname === "/users"
        ? "users"
        : null;
  const waiting = resource === "cases" && search.get("tab") === "waiting";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <img className="brand-mark" src={logo} alt="" />
          <span>
            Ø-Ticket
            <small>
              AI Agent-based
              <br />
              SOC Automation
            </small>
          </span>
        </Link>
        <nav>
          {menu
            .filter(([, , , needs]) => can(needs))
            .map(([path, label, icon]) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className={({ isActive }) =>
                  isActive || (path === "/alerts" && resource === "events")
                    ? "active"
                    : ""
                }
              >
                <span className="menu-icon">
                  <Icon name={icon} />
                </span>
                {label}
              </NavLink>
            ))}
          {adminMenu.some(([, , needs]) => can([needs])) && (
            <>
              <hr />
              <span className="menu-group">관리</span>
              {adminMenu
                .filter(([, , needs]) => can([needs]))
                .map(([path, label]) => (
                  <NavLink key={path} to={path}>
                    {label}
                  </NavLink>
                ))}
            </>
          )}
        </nav>
        <div className="sidebar-bottom">
          <span className="profile">
            <span className="profile-icon">
              <Icon name="profile" />
            </span>
            <span className="profile-text">
              <strong>{me.display_name}</strong>
              <span className="role-badge">{me.role}</span>
            </span>
          </span>
          <Link className="settings" to="/settings">
            <Icon name="settings" />
            설정
          </Link>
          <button
            type="button"
            className="settings"
            onClick={() => logout.mutate()}
          >
            로그아웃
          </button>
        </div>
      </aside>
      <div className="workspace">
        <main>
          <header className="page-heading">
            <div>
              <h1>
                {isHome
                  ? "DashBoard"
                  : page
                    ? page === "users"
                      ? "사용자 관리"
                      : "설정"
                    : resource
                      ? titles[resource]
                      : "페이지를 찾을 수 없습니다"}
              </h1>
            </div>
          </header>
          {page === "settings" ? (
            <SettingsPage me={me} />
          ) : page === "users" ? (
            <UsersPage />
          ) : !isHome && !resource ? null : dashboard.isPending ? (
            <p role="status">집계 불러오는 중…</p>
          ) : dashboard.error ? (
            <ErrorState
              error={dashboard.error}
              retry={() => void dashboard.refetch()}
            />
          ) : isHome ? (
            <DashboardView data={dashboard.data} />
          ) : (
            resource && <Overview resource={resource} data={dashboard.data} />
          )}
          {(resource === "alerts" || resource === "events") && (
            <div className="tabs">
              <NavLink to="/alerts">Alert</NavLink>
              <NavLink to="/events">Event</NavLink>
            </div>
          )}
          {resource === "cases" && (
            <>
              <div className="tabs">
                <Link
                  className={waiting ? "active" : ""}
                  to="/cases?tab=waiting"
                >
                  승인 대기 Incident
                </Link>
                <Link className={!waiting ? "active" : ""} to="/cases">
                  승인된 Case
                </Link>
              </div>
              <p className="notice">
                {waiting
                  ? "아직 Case가 아닌 승인 대기 Incident(awaiting_review)입니다. 사람이 승인하면 Case가 됩니다."
                  : "사람이 승인한 시점의 내용을 보관한 Case입니다."}
              </p>
            </>
          )}
          {resource && (
            <ListView
              key={`${resource}/${waiting}`}
              resource={waiting ? "incidents" : resource}
              waiting={waiting}
              summary={dashboard.data}
            />
          )}
        </main>
        <footer className="workspace-footer">
          0-Ticket SOC{" "}
          <a href="https://github.com/0-Ticket">https://github.com/0-Ticket</a>
        </footer>
      </div>
    </div>
  );
}
export default function App() {
  const location = useLocation();
  const me = useMe();
  const target = useLoginTarget();
  const path = location.pathname;
  if (me.isPending) return <p role="status">불러오는 중…</p>;
  if (me.error)
    return <ErrorState error={me.error} retry={() => void me.refetch()} />;
  const user = me.data;
  if (!user) {
    if (path === "/login") return <LoginPage />;
    if (path === "/signup") return <SignupPage />;
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  if (path === "/login" || path === "/signup")
    return (
      <Navigate to={user.must_change_password ? "/password" : target} replace />
    );
  if (user.must_change_password)
    return path === "/password" ? (
      <ForcedPasswordPage />
    ) : (
      <Navigate to="/password" replace />
    );
  if (path === "/password") return <Navigate to="/" replace />;
  return <Workspace me={user} />;
}
