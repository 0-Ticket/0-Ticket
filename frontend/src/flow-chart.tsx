import { useId } from "react";
import type { Dashboard } from "./api/generated/Dashboard";

type Stage = {
  label: string;
  unit: string;
  count: number;
  tip: string;
  mine?: boolean;
};
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
      tip: "수집됐지만 아직 정규화되지 않은 Alert/Event",
    },
    ...(mode === "scenario"
      ? [
          {
            label: "Ticket 전환 판단 대기",
            unit: "Alert",
            count: data.flow.l1_alerts_pending,
            // Design B-2 text.
            tip: "Ticket으로 만들지 L1이 판단하기를 기다리는 Alert (시나리오 모드에서만 사용)",
          },
        ]
      : []),
    {
      label: "위협 여부 판정 대기",
      unit: "Ticket",
      count: data.flow.l1_tickets_pending,
      tip: "L1이 위협 여부를 판정하기를 기다리는 Ticket",
    },
    {
      label: "L2 분석 대기",
      unit: "Ticket",
      count: data.ticket_status.escalated,
      tip: "L2 분석을 기다리는 Ticket",
    },
    {
      label: "L2 분석 중",
      unit: "Incident",
      count: data.incident_status.analyzing ?? 0,
      tip: "L2가 분석하고 있는 Incident",
    },
    {
      label: "내 승인 대기",
      unit: "Incident",
      count: data.incident_status.awaiting_review ?? 0,
      // Design B-2 text.
      tip: "분석이 끝나 사람이 승인·반려하기를 기다리는 Incident",
      mine: true,
    },
    {
      label: "대응 진행 중",
      unit: "Case",
      count: (cases.open ?? 0) + (cases.in_progress ?? 0),
      tip: "승인되어 대응이 진행 중인 Case",
    },
  ];
}
function FlowStage({ stage, max }: { stage: Stage; max: number }) {
  const tip = useId();
  return (
    // Focusable so the description is also reachable by keyboard (hover and focus show the tooltip).
    <li
      className={stage.mine ? "flow-stage mine" : "flow-stage"}
      tabIndex={0}
      aria-describedby={tip}
    >
      <div className="flow-bars">
        <strong>{stage.count.toLocaleString()}</strong>
        <span
          className="flow-bar"
          style={{ height: Math.round((stage.count / max) * BAR_MAX) }}
        />
      </div>
      <span className="flow-label">{stage.label}</span>
      <span className="flow-unit">{stage.unit}</span>
      <span role="tooltip" id={tip} className="flow-tip">
        {stage.tip}
      </span>
    </li>
  );
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
        <FlowStage key={s.label} stage={s} max={max} />
      ))}
    </ol>
  );
}
