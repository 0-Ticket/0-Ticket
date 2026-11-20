import type { ReactNode } from "react";
import type { IncidentDetail } from "./api/generated/IncidentDetail";
import type { TicketDetail } from "./api/generated/TicketDetail";
import { JsonViewer } from "./components/json-viewer";
import { Severity, Status } from "./badges";
import { IncidentGraph } from "./incident-graph";
import { ReviewActions } from "./review-actions";
import type { Resource } from "./api/client";

// Builds the in-app link for an id, or nothing when the account cannot open that screen.
export type LinkTo = (
  id: string,
  resource: Resource,
  label: string,
  name?: string,
) => ReactNode;

const when = (ms: number) => new Date(ms).toLocaleString("ko-KR");
const priorities = { high: "높음", medium: "중간", low: "낮음" } as const;

function Entities({
  entities,
}: {
  entities: { type: string; value: string; role: string | null }[];
}) {
  return (
    <>
      <h3>엔티티 · {entities.length}건</h3>
      {entities.length ? (
        <table className="detail-table">
          <thead>
            <tr>
              <th>type</th>
              <th>value</th>
              <th>role</th>
            </tr>
          </thead>
          <tbody>
            {entities.map((e, i) => (
              <tr key={i}>
                <td>{e.type}</td>
                <td>{e.value}</td>
                <td>{e.role ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>—</p>
      )}
    </>
  );
}

function History({
  rows,
  title,
}: {
  rows: [string, string | number][];
  title: string;
}) {
  return (
    <>
      <h3>{title}</h3>
      <table className="detail-table">
        <tbody>
          {rows.map(([name, value]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function TicketSections({
  data,
  link,
}: {
  data: TicketDetail;
  link: LinkTo;
}) {
  const { ticket, alerts, incident } = data;
  const verdict = ticket.verdict;
  return (
    <>
      <Severity value={data.severity} />
      {incident && (
        <>
          <h3>연결된 Incident</h3>
          <div className="summary-row">
            <strong>{incident.title}</strong>
            <Status value={incident.status} />
            <Severity value={incident.display_severity} />
            <div className="links">
              {link(incident.id, "incidents", "Incident 보기")}
            </div>
          </div>
        </>
      )}
      {alerts.length > 0 && (
        <>
          <h3>원본 Alert · {alerts.length}건</h3>
          <ul className="summary-list">
            {alerts.map((a) => (
              <li key={a.id}>
                <strong>{a.title}</strong>
                <code>{a.id}</code>
                <span>{when(a.time)}</span>
                <Severity value={a.severity} />
                {link(a.id, "alerts", "상세 보기")}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="links">
        {ticket.hunt_id && link(ticket.hunt_id, "hunts", "원본 Hunt")}
      </div>
      <h3>Ticket 판정과 근거</h3>
      {verdict ? (
        <section className="verdict">
          <h4>근거 검토</h4>
          <p>
            <strong>최종 판정 · {verdict.decision.toUpperCase()}</strong> ·
            신뢰도 {Math.round(verdict.confidence * 100)}%
          </p>
          <p>{verdict.reason}</p>
          <ul>
            {verdict.evidence_ids.map((id) => (
              <li key={id}>
                <code>{id}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <p>아직 판정되지 않았어요.</p>
      )}
      <Entities entities={ticket.entities} />
      <History
        title="Ticket 이력"
        rows={[
          ["생성", when(ticket.created_at)],
          ["마지막 갱신", when(ticket.updated_at)],
        ]}
      />
      <h3>Ticket 원본</h3>
      <JsonViewer value={ticket} />
    </>
  );
}

export function IncidentSections({
  data,
  link,
}: {
  data: IncidentDetail;
  link: LinkTo;
}) {
  const { incident, artifacts, tickets } = data;
  // Every round is kept; the screen shows recommendations of the newest round only (D-045, D-072).
  const latest = artifacts.reduce<(typeof artifacts)[number] | null>(
    (a, b) => (a === null || b.analysis_round > a.analysis_round ? b : a),
    null,
  );
  const recommendations = latest
    ? data.proposals
        .filter((p) => p.artifact_id === latest.id)
        .sort((a, b) => a.seq - b.seq)
    : [];
  return (
    <>
      <h3>사건 요약</h3>
      <p>{incident.summary ?? "분석이 끝나면 여기에 표시돼요."}</p>
      {latest && (
        <>
          <h3>영향</h3>
          <p>{latest.impact}</p>
        </>
      )}
      <h3>소속 Ticket · {tickets.length}건</h3>
      <ul className="summary-list">
        {tickets.map((t) => (
          <li key={t.id}>
            <strong>{t.title}</strong>
            <code>{t.id}</code>
            {link(t.id, "tickets", "Ticket 상세", `${t.title} Ticket 상세`)}
          </li>
        ))}
      </ul>
      <Entities entities={incident.entities} />
      <h3>Ticket 연결 그래프</h3>
      <IncidentGraph
        incident={incident}
        ticketGraphs={data.ticket_graphs}
        titles={Object.fromEntries(tickets.map((t) => [t.id, t.title]))}
      />
      {recommendations.length > 0 && (
        <>
          <h3>권고 조치 · {recommendations.length}건</h3>
          {recommendations.map((p) => (
            <div className="proposal" key={p.id}>
              <span className="kind">
                {p.kind === "response" ? "대응" : "탐지 룰"}
              </span>
              {p.priority && <span>우선순위 {priorities[p.priority]}</span>}
              <strong>{p.title}</strong>
              <pre>{p.detail}</pre>
              {p.rationale && (
                <p>
                  <em>왜 필요한가</em> {p.rationale}
                </p>
              )}
            </div>
          ))}
        </>
      )}
      <h3>Incident</h3>
      <JsonViewer value={incident} />
      <h3>라운드별 분석 보고서</h3>
      {artifacts.length ? (
        artifacts.map((a) => (
          <section key={a.id}>
            <h4>분석 라운드 {a.analysis_round}</h4>
            <JsonViewer value={a} />
          </section>
        ))
      ) : (
        <p>분석 보고서가 없습니다.</p>
      )}
      <History
        title="분석 이력"
        rows={[
          ["분석 라운드", incident.analysis_round],
          ["검토 라운드", incident.review_round],
          ["생성", when(incident.created_at)],
          ["마지막 갱신", when(incident.updated_at)],
        ]}
      />
      <ReviewActions id={incident.id} status={incident.status} />
    </>
  );
}
