import type { Dashboard } from "./api/generated/Dashboard";

type Stage = { label: string; unit: string; count: number; mine?: boolean };
const BAR_MAX = 48; // design: 6px per item, 8 items = 48px
// Design 21a (scenario mode, 7 stages) and 21b (auto mode, 6 stages). Auto mode has no
// "Ticket 전환 판단 대기" stage because every Alert becomes a Ticket without a decision.
export function stages(data: Dashboard, mode: "auto" | "scenario"): Stage[] {
  const cases = data.case_status;
  return [
    {
      label: "정규화 대기",
      unit: "Alert/Event",
      count: data.flow.normalization_pending,
    },
    ...(mode === "scenario"
      ? [
          {
            label: "Ticket 전환 판단 대기",
            unit: "Alert",
            count: data.flow.l1_alerts_pending,
          },
        ]
      : []),
    {
      label: "위협 여부 판정 대기",
      unit: "Ticket",
      count: data.flow.l1_tickets_pending,
    },
    {
      label: "L2 분석 대기",
      unit: "Ticket",
      count: data.ticket_status.escalated,
    },
    {
      label: "L2 분석 중",
      unit: "Incident",
      count: data.incident_status.analyzing ?? 0,
    },
    {
      label: "내 승인 대기",
      unit: "Incident",
      count: data.incident_status.awaiting_review ?? 0,
      mine: true,
    },
    {
      label: "대응 진행 중",
      unit: "Case",
      count: (cases.open ?? 0) + (cases.in_progress ?? 0),
    },
  ];
}
export function FlowChart({
  data,
  mode,
}: {
  data: Dashboard;
  mode: "auto" | "scenario";
}) {
  const list = stages(data, mode);
  const max = Math.max(1, ...list.map((s) => s.count));
  return (
    <ol
      className="flow-chart"
      aria-label="처리 흐름"
      style={{ "--stages": list.length } as React.CSSProperties}
    >
      {list.map((s) => (
        <li key={s.label} className={s.mine ? "flow-stage mine" : "flow-stage"}>
          <div className="flow-bars">
            <strong>{s.count.toLocaleString()}</strong>
            <span
              className="flow-bar"
              style={{ height: Math.round((s.count / max) * BAR_MAX) }}
            />
          </div>
          <span className="flow-label">{s.label}</span>
          <span className="flow-unit">{s.unit}</span>
        </li>
      ))}
    </ol>
  );
}
