import type { Incident } from '../contracts';
import { Badge, ObjectId, Timestamp } from './contract-display';

export function IncidentList({ incidents }: { incidents: Incident[] }) {
  return (
    <ol className="space-y-3">
      {incidents.map((incident) => {
        const excluded = incident.members.filter((member) => member.excluded).length;
        return (
          <li key={incident.incident_id} className="rounded-lg border border-border p-4">
            <article className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <ObjectId
                  value={incident.incident_id}
                  href={`/incidents/${encodeURIComponent(incident.incident_id)}`}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Badge value={incident.status} />
                  <Badge value={null} severity={incident.severity_id} />
                  <Badge value={incident.created_by} />
                </div>
              </div>
              <p className="font-medium whitespace-pre-wrap break-words">{incident.title}</p>
              <p className="text-sm whitespace-pre-wrap break-words">
                요약: {incident.summary ?? '없음'}
              </p>
              <p className="text-sm">
                묶음 항목 {incident.members.length - excluded}건 · 제외 {excluded}건
              </p>
              <p className="text-sm">
                전술: {incident.tactics.length ? incident.tactics.join(', ') : '없음'}
              </p>
              <div className="flex flex-wrap gap-x-6 text-xs">
                <span>
                  처음 <Timestamp value={incident.first_seen} />
                </span>
                <span>
                  마지막 <Timestamp value={incident.last_seen} />
                </span>
              </div>
            </article>
          </li>
        );
      })}
    </ol>
  );
}
