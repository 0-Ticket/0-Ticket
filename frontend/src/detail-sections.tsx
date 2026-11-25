import type { ReactNode } from "react";
import type { TicketDetail } from "./api/generated/TicketDetail";
import { JsonViewer } from "./components/json-viewer";
import { Severity, Status } from "./badges";
import type { Resource } from "./api/client";

// Builds the in-app link for an id, or nothing when the account cannot open that screen.
export type LinkTo = (
  id: string,
  resource: Resource,
  label: string,
  name?: string,
) => ReactNode;

const when = (ms: number) => new Date(ms).toLocaleString("ko-KR");

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
          <p>근거 {verdict.evidence_ids.length}개</p>
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
