import { Fragment } from "react";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { Severity } from "../badges";
import { useLink } from "../links";
import { Clip } from "./kit";
import { latestArtifact } from "./model";

const priorities = { high: "높음", medium: "중간", low: "낮음" } as const;

export function OverviewTab({
  data,
  showTickets,
}: {
  data: IncidentDetail;
  showTickets: () => void;
}) {
  const link = useLink();
  const { incident, tickets } = data;
  // Every round is kept; the overview shows the recommendations of the newest round only (D-045, D-072).
  const latest = latestArtifact(data.artifacts);
  const recommendations = latest
    ? data.proposals
        .filter((p) => p.artifact_id === latest.id)
        .sort((a, b) => a.seq - b.seq)
    : [];
  return (
    <>
      <section className="card">
        <h3>사건 요약</h3>
        <p>{incident.summary ?? "분석이 끝나면 여기에 표시돼요."}</p>
        {latest && (
          <>
            <h3>영향</h3>
            <p>{latest.impact}</p>
          </>
        )}
      </section>
      <section className="card">
        <div className="incident-section-head">
          <h3>{`소속 Ticket · ${tickets.length}건`}</h3>
          {tickets.length > 0 && (
            <button
              type="button"
              className="incident-link"
              onClick={showTickets}
            >
              전체 보기
            </button>
          )}
        </div>
        {tickets.length ? (
          <ul className="summary-list">
            {tickets.slice(0, 5).map((t) => (
              <li key={t.id}>
                <strong>{t.title}</strong>
                <Clip text={t.id} label="Ticket ID" />
                <Severity value={t.severity} />
                {link(t.id, "tickets", "Ticket 상세", `${t.title} Ticket 상세`)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="empty">연결된 Ticket이 없습니다.</p>
        )}
      </section>
      {recommendations.length > 0 && (
        <section className="card">
          <h3>{`권고 조치 · ${recommendations.length}건`}</h3>
          {recommendations.map((p, i) => (
            <Fragment key={p.id}>
              <div className="incident-recommendation">
                <span className="kind">
                  {p.kind === "response" ? "대응" : "탐지 룰"}
                </span>
                {p.priority && (
                  <span>{`우선순위 ${priorities[p.priority]}`}</span>
                )}
                <strong>{p.title}</strong>
                <p className="incident-detail">{p.detail}</p>
                {p.rationale && (
                  <p className="incident-detail">{p.rationale}</p>
                )}
              </div>
              {i < recommendations.length - 1 && (
                <hr className="incident-rule" />
              )}
            </Fragment>
          ))}
        </section>
      )}
    </>
  );
}
