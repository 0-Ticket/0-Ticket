import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { JsonViewer } from "../components/json-viewer";
import { when } from "./model";

export function HistoryTab({ data }: { data: IncidentDetail }) {
  const { incident } = data;
  const rounds = [...data.artifacts].sort(
    (a, b) => b.analysis_round - a.analysis_round,
  );
  return (
    <>
      <section className="card">
        <h3>라운드별 분석 보고서</h3>
        {rounds.length ? (
          rounds.map((a, i) => (
            <details key={a.id} className="incident-round" open={i === 0}>
              <summary>
                <strong>{`분석 라운드 ${a.analysis_round}`}</strong>
                <span className="date">{when(a.created_at)}</span>
              </summary>
              <JsonViewer value={a} />
            </details>
          ))
        ) : (
          <p className="empty">분석 보고서가 없습니다.</p>
        )}
      </section>
      <section className="card">
        <h3>분석 이력</h3>
        <table className="detail-table">
          <tbody>
            {(
              [
                ["분석 라운드", incident.analysis_round],
                ["검토 라운드", incident.review_round],
                ["생성", when(incident.created_at)],
                ["마지막 갱신", when(incident.updated_at)],
              ] as [string, string | number][]
            ).map(([name, value]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
