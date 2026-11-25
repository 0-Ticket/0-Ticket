import { Link } from "react-router";
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
import type { Resource } from "./api/client";
import type { Dashboard } from "./api/generated/Dashboard";
import { useCan } from "./auth/session";
import { Severity } from "./badges";
import { statusNames } from "./constants";
import { FlowChart } from "./flow-chart";
import { severityLabel } from "./severity";

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
      name: risk ? severityLabel(Number(key)) : (statusNames[key] ?? key),
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
        <Link key={item.id} to={`/incidents/${item.id}`}>
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
          <span>{severityLabel(level)}</span>
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
export function DashboardView({
  data,
  mode,
}: {
  data: Dashboard;
  mode: "default" | "scenario";
}) {
  // Everything on the dashboard is shown only if the account may read what it summarizes.
  const can = useCan();
  const nothing = !can(
    "alert.read",
    "event.read",
    "ticket.read",
    "incident.read",
    "case.read",
    "hunt.read",
  );
  if (nothing)
    return (
      <p className="empty">
        이 계정이 읽을 수 있는 집계가 없어요. 필요한 권한은 관리자에게 요청해
        주세요.
      </p>
    );
  return (
    <>
      <FlowChart data={data} mode={mode} />
      <div className="dashboard-grid">
        {(can("ticket.read") || can("hunt.read")) && (
          <div className="dashboard-stack">
            {can("ticket.read") && (
              <article className="card">
                <div className="card-heading">
                  <h3>Tickets by Risk Level</h3>
                  <Link to="/tickets">전체 보기 →</Link>
                </div>
                <p className="chart-caption">전체 {data.flow.tickets}건</p>
                <RiskBars counts={data.ticket_severity} />
              </article>
            )}
            {can("hunt.read") && (
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
            )}
          </div>
        )}
        {can("incident.read") && (
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
        )}
      </div>
    </>
  );
}
export function Overview({
  resource,
  data,
}: {
  resource: Resource;
  data: Dashboard;
}) {
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
