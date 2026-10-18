import type { Incident } from '../contracts';
import { severityTones, toneRails } from '../lib/display';
import { cn } from '../lib/utils';
import { Badge, ObjectId, ReviewStateBadge, Timestamp } from './contract-display';

export function IncidentList({ incidents }: { incidents: Incident[] }) {
  return (
    <ol className="space-y-3">
      {incidents.map((incident) => {
        const excluded = incident.members.filter((member) => member.excluded).length;
        return (
          <li key={incident.incident_id}>
            <article
              className={cn(
                'min-w-0 overflow-hidden rounded-lg border border-l-4 border-border bg-card shadow-card',
                toneRails[severityTones[incident.severity_id] ?? 'neutral'],
              )}
            >
              <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
                <ObjectId
                  value={incident.incident_id}
                  href={`/incidents/${encodeURIComponent(incident.incident_id)}`}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Badge value={null} severity={incident.severity_id} />
                  <Badge value={incident.status} />
                  <Badge value={incident.created_by} />
                  <ReviewStateBadge value={incident.review_state} />
                </div>
              </header>
              <div className="grid min-w-0 gap-4 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0 space-y-1">
                  <p className="font-semibold whitespace-pre-wrap break-words">{incident.title}</p>
                  <p className="text-sm whitespace-pre-wrap break-words text-muted-foreground">
                    요약: {incident.summary ?? '없음'}
                  </p>
                  <p className="text-xs break-words text-muted-foreground">
                    전술: {incident.tactics.length ? incident.tactics.join(', ') : '없음'}
                  </p>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground md:min-w-56 md:border-l md:border-border md:pl-4">
                  <p className="text-sm font-semibold text-foreground">
                    묶음 항목 {incident.members.length - excluded}건 · 제외 {excluded}건
                  </p>
                  <p>
                    처음 <Timestamp value={incident.first_seen} />
                  </p>
                  <p>
                    마지막 <Timestamp value={incident.last_seen} />
                  </p>
                </div>
              </div>
            </article>
          </li>
        );
      })}
    </ol>
  );
}
