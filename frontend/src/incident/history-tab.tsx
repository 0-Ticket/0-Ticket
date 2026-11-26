import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { Severity } from "../badges";
import { JsonViewer } from "../components/json-viewer";
import { when } from "./model";

const verdicts = {
  not_threat: "위협 아님",
  attempted: "공격 시도",
  succeeded: "공격 성공",
  inconclusive: "판단 보류",
} as const;

// One entry per saved analysis round. There is no stored data for per-round change counts or review events (D-076, D-081).
export function HistoryTab({ data }: { data: IncidentDetail }) {
  const { incident } = data;
  const rounds = [...data.artifacts].sort(
    (a, b) => b.analysis_round - a.analysis_round,
  );
  if (!rounds.length)
    return (
      <section className="card">
        <h3>분석 이력</h3>
        <p className="empty">분석 보고서가 없습니다.</p>
      </section>
    );
  return (
    <section className="card">
      <div className="incident-section-head">
        <h3>{`분석 이력 · ${rounds.length}라운드`}</h3>
        <span className="incident-count">{`분석 ${incident.analysis_round}회 · 검토 ${incident.review_round}회`}</span>
      </div>
      <ol className="incident-timeline" aria-label="분석 라운드 타임라인">
        {rounds.map((a) => (
          <li key={a.id}>
            <div className="incident-timeline-head">
              <strong>{`Round ${a.analysis_round}`}</strong>
              <span className="badge">{verdicts[a.verdict]}</span>
              <Severity value={a.assessed_severity} />
              <span className="date">{when(a.created_at)}</span>
            </div>
            <p className="incident-detail">{a.summary}</p>
          </li>
        ))}
      </ol>
      <details className="incident-raw">
        <summary>원본 보기(고급)</summary>
        {rounds.map((a) => (
          <details key={a.id} className="incident-round">
            <summary>{`분석 라운드 ${a.analysis_round}`}</summary>
            <JsonViewer value={a} />
          </details>
        ))}
      </details>
    </section>
  );
}
