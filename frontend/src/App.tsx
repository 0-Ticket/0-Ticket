import { useEffect, useRef } from "react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router";
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
import { Button } from "./components/ui/button";
import {
  get,
  itemId,
  itemTitle,
  itemStatus,
  itemSeverity,
  seedSource,
} from "./api/client";
import type { Resource, Page, Item, Detail } from "./api/client";
import type { Dashboard } from "./api/generated/Dashboard";

const menu = [
  ["/", "대시보드", "◫"],
  ["/alerts", "Alert/Event", "≋"],
  ["/tickets", "Ticket", "▤"],
  ["/incidents", "Incident", "◈"],
  ["/cases", "Case", "▣"],
  ["/hunts", "Hunting", "◎"],
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
    "awaiting_review",
    "confirmed",
    "human_handling",
    "dismissed",
  ],
  cases: ["open", "in_progress", "resolved"],
  hunts: ["pending", "confirmed", "rejected", "inconclusive", "failed"],
};
const colors = [
  "#94a3b8",
  "#94a3b8",
  "#38bdf8",
  "#eab308",
  "#f97316",
  "#ef4444",
  "#a855f7",
];
const severityNames = ["미상", "정보", "낮음", "보통", "높음", "심각", "치명"];
function Severity({ value }: { value: number | null }) {
  return value === null ? (
    <span>—</span>
  ) : (
    <span className={`badge severity s${value}`}>
      {value === 0 ? "미상" : `${value} · ${severityNames[value]}`}
    </span>
  );
}
function Status({ value }: { value: string }) {
  return (
    <span className={`badge status-${value}`}>
      {statusNames[value] ?? value}
    </span>
  );
}
function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <div role="alert" className="empty">
      <p>{error.message}</p>
      <Button variant="outline" onClick={retry}>
        다시 시도
      </Button>
    </div>
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
      name: risk
        ? `${key} ${severityNames[Number(key)]}`
        : (statusNames[key] ?? key),
      value,
      key,
    }));
  if (risk) data.reverse();
  if (data.every((d) => d.value === 0))
    return (
      <p className="empty">
        {risk && counts["0"]
          ? `알려진 위험도 없음 · 미상 ${counts["0"]}건`
          : "데이터 없음"}
      </p>
    );
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
              dataKey="value"
              name="건수"
              radius={horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0]}
              maxBarSize={40}
            >
              {data.map((d) => (
                <Cell
                  key={d.key}
                  fill={risk ? colors[Number(d.key)] : "#3b82f6"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="chart-caption">
        {data.map((d) => `${d.name} ${d.value}건`).join(" · ")}
        {risk ? ` · 미상 ${counts["0"] ?? 0}건` : ""}
      </p>
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
    { name: "성공", value: counts.succeeded },
    { name: "실패", value: counts.failed },
  ];
  return (
    <article className="card">
      <h3>{name} 정규화</h3>
      <div className="donut">
        <ResponsiveContainer
          width="100%"
          height={140}
          initialDimension={{ width: 250, height: 140 }}
        >
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              innerRadius={45}
              outerRadius={62}
              stroke="none"
            >
              {data.map((d, i) => (
                <Cell key={d.name} fill={i ? "#f97316" : "#3b82f6"} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <strong>
          {counts.success_ratio === null
            ? "데이터 없음"
            : `${Math.round(counts.success_ratio * 100)}%`}
        </strong>
      </div>
      <p className="chart-caption">
        성공 {counts.succeeded} · 실패 {counts.failed} · 대기 {counts.pending}
      </p>
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
function DashboardView({ data }: { data: Dashboard }) {
  const steps = [
    ["normalization_pending", "정규화 대기"],
    ["l1_alerts_pending", "L1 대기 Alert"],
    ["l1_tickets_pending", "L1 대기 Ticket"],
    ["tickets", "Ticket 생성"],
    ["incidents", "Incident 생성"],
    ["cases", "Case 이관"],
  ];
  return (
    <>
      <section className="flow-grid">
        {steps.map(([key, label], i) => (
          <article className="kpi" key={key}>
            <span>
              {String(i + 1).padStart(2, "0")} / {label}
            </span>
            <strong>
              {(data.flow[key] ?? 0).toLocaleString()}
              <small>건</small>
            </strong>
            <p>{i < 3 ? "현재 대기" : "보관된 전체 건수"}</p>
          </article>
        ))}
      </section>
      <div className="dashboard-grid">
        <article className="card span-2">
          <div className="card-heading">
            <h3>Ticket 위험도 분포</h3>
            <Link to="/tickets">전체 보기 →</Link>
          </div>
          <Bars counts={data.ticket_severity} risk />
        </article>
        <article className="card hunting-card">
          <h3>위협 헌팅</h3>
          <strong>
            {data.hunting.total}
            <small> 가설</small>
          </strong>
          <p>Ticket 승격 {data.hunting.promoted}건</p>
          <div className="progress">
            <span
              style={{ width: `${(data.hunting.promotion_ratio ?? 0) * 100}%` }}
            />
          </div>
          <p className="chart-caption">
            전체 가설 대비 승격{" "}
            {data.hunting.promotion_ratio === null
              ? "데이터 없음"
              : `${Math.round(data.hunting.promotion_ratio * 100)}%`}
          </p>
          <Link to="/hunts">헌팅 결과 보기 →</Link>
        </article>
        <article className="card span-2">
          <div className="card-heading">
            <h3>분석 결과가 있는 Incident</h3>
            <Link to="/incidents">전체 보기 →</Link>
          </div>
          <SmallList items={data.analyzed_incidents} />
        </article>
        <article className="card">
          <h3>위험 높은 Incident · Top 10</h3>
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
        <Bars counts={data.incident_status} horizontal />
      </article>
    );
  if (resource === "hunts")
    return (
      <article className="card">
        <h3>
          전체 가설 {data.hunting.total}건 · Ticket 승격 {data.hunting.promoted}
          건
        </h3>
        <p>
          전체 가설 대비 승격 비율:{" "}
          {data.hunting.promotion_ratio === null
            ? "데이터 없음"
            : `${Math.round(data.hunting.promotion_ratio * 100)}%`}
        </p>
        <Bars counts={data.hunting.statuses} />
      </article>
    );
  return null;
}
function SafeJson({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
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
  const seed =
    "seed_source" in data
      ? data.seed_source
      : "hunt" in data
        ? data.hunt.details.seed_source
        : null;
  return (
    <>
      {typeof seed === "string" && (
        <p className="seed-note">개발 시드 · {seed}</p>
      )}
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
          <SafeJson value={data.ticket} />
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
          <SafeJson value={data.incident} />
          <h3>라운드별 분석 보고서</h3>
          {data.artifacts.length ? (
            data.artifacts.map((a) => (
              <section key={a.id}>
                <h4>분석 라운드 {a.analysis_round}</h4>
                <SafeJson value={a} />
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
          <SafeJson value={data.case} />
        </>
      )}
      {"raw_record" in data && (
        <>
          <Status value={data.normalize_status} />
          {data.error_code && <p>실패 코드: {data.error_code}</p>}
          <h3>{data.record ? "정규화 결과 · OCSF" : "정규화 결과 없음"}</h3>
          {data.record && <SafeJson value={data.record} />}
          <h3>수집 원본</h3>
          <SafeJson value={data.raw_record} />
        </>
      )}
      {"hunt" in data && (
        <>
          <div className="links">
            {data.ticket_id &&
              internalLink(data.ticket_id, "tickets", "승격 Ticket")}
          </div>
          <h3>가설과 검증 결과</h3>
          <SafeJson value={data.hunt} />
          <h3>검증 과정 · 실행 요약</h3>
          {data.runs.length ? (
            data.runs.map((r) => (
              <div key={r.run_id} className="proposal">
                <strong>
                  {r.task ?? "실행"} · {r.outcome}
                </strong>
                <SafeJson value={r} />
              </div>
            ))
          ) : (
            <p>실행 기록이 없습니다.</p>
          )}
          <h3>ATT&amp;CK 기법</h3>
          <SafeJson value={data.techniques} />
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
          <h2 id="detail-title">{titles[resource]} 상세</h2>
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
function ListView({
  resource,
  waiting = false,
}: {
  resource: Resource;
  waiting?: boolean;
}) {
  const [search, setSearch] = useSearchParams();
  const status = waiting ? "awaiting_review" : (search.get("status") ?? "");
  const params = new URLSearchParams({ limit: "25" });
  for (const key of ["cursor", "origin", "severity"])
    if (search.get(key) && (resource === "tickets" || key === "cursor"))
      params.set(key, search.get(key)!);
  if (status) params.set("status", status);
  const path = `${resource}?${params}`;
  const query = useQuery({
    queryKey: ["list", path],
    queryFn: ({ signal }) => get<Page>(path, signal),
  });
  function change(key: string, value: string) {
    const next = new URLSearchParams(search);
    next.delete("cursor");
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
  return (
    <section className="card list-card">
      <div className="list-toolbar">
        <h3>{waiting ? "승인 대기 Incident" : titles[resource]} 목록</h3>
        <div className="filters">
          {!waiting && (
            <label>
              상태
              <select
                aria-label="상태 필터"
                value={status}
                onChange={(e) => change("status", e.target.value)}
              >
                <option value="">전체 상태</option>
                {states[resource].map((s) => (
                  <option value={s} key={s}>
                    {statusNames[s]}
                  </option>
                ))}
              </select>
            </label>
          )}
          {resource === "tickets" && (
            <>
              <label>
                출처
                <select
                  aria-label="출처 필터"
                  value={search.get("origin") ?? ""}
                  onChange={(e) => change("origin", e.target.value)}
                >
                  <option value="">전체 출처</option>
                  {["auto", "scenario", "l1", "l3"].map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                위험도
                <select
                  aria-label="위험도 필터"
                  value={search.get("severity") ?? ""}
                  onChange={(e) => change("severity", e.target.value)}
                >
                  <option value="">전체 위험도</option>
                  {severityNames.map((s, i) => (
                    <option key={i} value={i}>
                      {i === 0 ? "미상" : `${i} ${s}`}
                    </option>
                  ))}
                </select>
              </label>
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
                  <th>구분</th>
                  <th>시각</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((item) => (
                  <tr key={itemId(item)} onClick={() => select(item)}>
                    <td>
                      <button className="record-link">{itemTitle(item)}</button>
                      <small className="record-id">{itemId(item)}</small>
                    </td>
                    <td>
                      <Status value={itemStatus(item)} />
                    </td>
                    <td>
                      <Severity value={itemSeverity(item)} />
                    </td>
                    <td>
                      {seedSource(item) ? (
                        <span className="badge seed">개발 시드</span>
                      ) : "origin" in item ? (
                        item.origin
                      ) : (
                        "—"
                      )}
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
        <span>최신순 · 페이지당 25건</span>
        <div>
          <Button
            variant="outline"
            size="sm"
            disabled={!search.has("cursor")}
            onClick={() => change("cursor", "")}
          >
            처음
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!query.data?.next_cursor || query.isFetching}
            onClick={() => change("cursor", query.data?.next_cursor ?? "")}
          >
            다음 페이지
          </Button>
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
export default function App() {
  const location = useLocation();
  const [search] = useSearchParams();
  const slug = location.pathname.slice(1);
  const resource = (
    Object.hasOwn(titles, slug) ? slug : null
  ) as Resource | null;
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => get<Dashboard>("dashboard", signal),
  });
  const isHome = location.pathname === "/";
  const waiting = resource === "cases" && search.get("tab") === "waiting";
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <span className="brand-mark">0</span>
          <span>
            0-Ticket<small>SECURITY OPERATIONS</small>
          </span>
        </Link>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {menu.map(([path, label, icon]) => (
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
              <span aria-hidden="true">{icon}</span>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="workspace-status">
            <span />
            읽기 전용 워크스페이스
          </div>
          <button disabled>로그인 · 준비 중</button>
          <button disabled>설정 · 준비 중</button>
          <small>0-Ticket SOC</small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            Workspace <b>/</b> {resource ? titles[resource] : "Overview"}
          </span>
          <span className="readonly">조회 전용</span>
        </header>
        <main>
          <header className="page-heading">
            <div>
              <span className="eyebrow">SECURITY OPERATIONS CENTER</span>
              <h1>
                {isHome
                  ? "대시보드"
                  : resource
                    ? titles[resource]
                    : "페이지를 찾을 수 없습니다"}
              </h1>
              <p>
                {isHome
                  ? "알럿부터 사고 분석까지, 보관된 전체 자료의 현재 상태를 확인하세요."
                  : "분석 결과를 조회하고 연결된 원본과 근거를 확인하세요."}
              </p>
            </div>
            <Button variant="outline" onClick={() => void dashboard.refetch()}>
              집계 새로고침 ↻
            </Button>
          </header>
          <p className="scope-note">
            전체 보관 자료 기준 · 개발 시드 포함 · 시간대{" "}
            {Intl.DateTimeFormat().resolvedOptions().timeZone}
          </p>
          {dashboard.isPending ? (
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
            />
          )}
        </main>
        <footer className="workspace-footer">
          0-Ticket SOC <span>판정은 에이전트, 확정은 사람.</span>
        </footer>
      </div>
    </div>
  );
}
