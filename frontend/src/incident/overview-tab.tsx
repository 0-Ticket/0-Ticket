import { Fragment } from "react";
import { Link } from "react-router";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { Severity } from "../badges";
import { useHref } from "../links";
import { entityRows, latestArtifact, when } from "./model";

const priorities = { high: "높음", medium: "중간", low: "낮음" } as const;
const TICKETS_SHOWN = 5;

export function OverviewTab({
  data,
  showTickets,
}: {
  data: IncidentDetail;
  showTickets: () => void;
}) {
  const href = useHref();
  const { incident, tickets } = data;
  // Every round is kept; the overview shows the recommendations of the newest round only (D-045, D-072).
  const latest = latestArtifact(data.artifacts);
  const recommendations = latest
    ? data.proposals
        .filter((p) => p.artifact_id === latest.id)
        .sort((a, b) => a.seq - b.seq)
    : [];
  // The entities that most tickets share; equal counts go by kind, then value.
  const key = [...entityRows(data)]
    .sort(
      (a, b) =>
        b.tickets - a.tickets ||
        a.type.localeCompare(b.type) ||
        a.value.localeCompare(b.value),
    )
    .slice(0, 3);
  return (
    <div className="incident-overview">
      <div role="region" aria-label="사건 개요" className="incident-column">
        <section className="card">
          <h3>사건 요약</h3>
          <p>{incident.summary ?? "분석이 끝나면 여기에 표시돼요."}</p>
          {latest?.impact && (
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
              {tickets.slice(0, TICKETS_SHOWN).map((t) => {
                const to = href(t.id, "tickets");
                const row = (
                  <>
                    <strong>{t.title}</strong>
                    <span className="date">{`${when(t.created_at)} · 근거 ${t.evidence_count}개`}</span>
                    {t.decision && (
                      <span className="badge decision">{t.decision}</span>
                    )}
                    <Severity value={t.severity} />
                  </>
                );
                return (
                  <li key={t.id}>
                    {to ? (
                      <Link
                        to={to}
                        className="incident-row-link"
                        aria-label={`${t.title} Ticket 상세`}
                      >
                        {row}
                      </Link>
                    ) : (
                      <div className="incident-row-link">{row}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="empty">연결된 Ticket이 없습니다.</p>
          )}
        </section>
      </div>
      <aside aria-label="핵심 엔티티와 권고 조치" className="incident-column">
        <section className="card">
          <h3>핵심 엔티티</h3>
          {key.length ? (
            <ul className="summary-list">
              {key.map((e) => (
                <li key={e.key}>{`${e.type} · ${e.value}`}</li>
              ))}
            </ul>
          ) : (
            <p className="empty">엔티티가 없습니다.</p>
          )}
        </section>
        {recommendations.length > 0 && (
          <section className="card">
            <h3>{`권고 조치 · ${recommendations.length}건`}</h3>
            {recommendations.map((p, i) => (
              <Fragment key={p.id}>
                <div className="incident-recommendation">
                  <div className="incident-chips">
                    {p.priority && (
                      <span className="badge">{priorities[p.priority]}</span>
                    )}
                    <span className="badge">
                      {p.kind === "response" ? "대응" : "탐지 룰"}
                    </span>
                  </div>
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
      </aside>
    </div>
  );
}
