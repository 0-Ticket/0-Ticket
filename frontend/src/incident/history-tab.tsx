import type {
  IncidentDetail,
  IncidentReview,
} from "../api/generated/IncidentDetail";
import { Severity } from "../badges";
import { JsonViewer } from "../components/json-viewer";
import { when } from "./model";

const verdicts = {
  not_threat: "위협 아님",
  attempted: "공격 시도",
  succeeded: "공격 성공",
  inconclusive: "판단 보류",
} as const;

// One entry per saved analysis round, with the review events (approve/reject) between them (D-082).
// There is no stored data for per-round change counts. Reviews are placed by analysis_round: above the
// nearest round at or below it, or at the bottom when there is none. Same place: newest first.
function placeReviews(rounds: number[], reviews: IncidentReview[]) {
  const placed = new Map<number | null, IncidentReview[]>();
  for (const item of reviews) {
    const at = rounds.find((n) => n <= item.analysis_round) ?? null;
    placed.set(at, [item, ...(placed.get(at) ?? [])]);
  }
  return placed;
}
const decisions = {
  approve: "Incident 승인",
  reject: "Incident 반려",
} as const;

function ReviewEvent({ item }: { item: IncidentReview }) {
  return (
    <li className="incident-timeline-review">
      <div className="incident-timeline-head">
        <strong>{decisions[item.decision]}</strong>
        <span className="badge">{`검토 ${item.review_round}회`}</span>
        <span>{item.decided_by}</span>
        <span className="date">{when(item.created_at)}</span>
      </div>
      {item.reason && (
        <p className="incident-detail">{`사유: ${item.reason}`}</p>
      )}
    </li>
  );
}

export function HistoryTab({ data }: { data: IncidentDetail }) {
  const { incident } = data;
  const rounds = [...data.artifacts].sort(
    (a, b) => b.analysis_round - a.analysis_round,
  );
  const placed = placeReviews(
    rounds.map((a) => a.analysis_round),
    data.reviews ?? [],
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
        {rounds.map((a) => [
          ...(placed.get(a.analysis_round) ?? []).map((item) => (
            <ReviewEvent key={`${item.review_round}`} item={item} />
          )),
          <li key={a.id}>
            <div className="incident-timeline-head">
              <strong>{`Round ${a.analysis_round}`}</strong>
              <span className="badge">{verdicts[a.verdict]}</span>
              <Severity value={a.assessed_severity} />
              <span className="date">{when(a.created_at)}</span>
            </div>
            <p className="incident-detail">{a.summary}</p>
          </li>,
        ])}
        {(placed.get(null) ?? []).map((item) => (
          <ReviewEvent key={`${item.review_round}`} item={item} />
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
