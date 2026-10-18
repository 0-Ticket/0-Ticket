import type { HuntFinding } from '../contracts';
import { severityTones, toneRails } from '../lib/display';
import { cn } from '../lib/utils';
import { Badge, ObjectId, Timestamp } from './contract-display';
import { ToneBadge } from './ui/badge';

// C17 flags shown as received. Nothing here decides anomaly, severity or grouping.
export function HuntBadges({ hunt }: { hunt: HuntFinding }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge value={null} severity={hunt.severity_id} />
      <ToneBadge tone={hunt.is_anomaly ? 'warning' : 'neutral'}>
        {hunt.is_anomaly ? '이상 징후' : '이상 없음'}
      </ToneBadge>
      <Badge value={hunt.method} />
      {hunt.needs_human && <ToneBadge tone="purple">사람 확인 필요</ToneBadge>}
    </div>
  );
}

export function HuntIncident({ id }: { id: string | null }) {
  return id === null ? (
    <span>Incident: 없음</span>
  ) : (
    <span className="flex flex-wrap items-center gap-1">
      Incident <ObjectId value={id} href={`/incidents/${encodeURIComponent(id)}`} />
    </span>
  );
}

export function HuntList({ hunts }: { hunts: HuntFinding[] }) {
  return (
    <ol className="space-y-3">
      {hunts.map((hunt) => (
        <li key={hunt.hunt_id}>
          <article
            data-testid="hunt-row"
            className={cn(
              'min-w-0 overflow-hidden rounded-lg border border-l-4 border-border bg-card shadow-card',
              toneRails[severityTones[hunt.severity_id] ?? 'neutral'],
            )}
          >
            <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
              <ObjectId value={hunt.hunt_id} href={`/hunts/${encodeURIComponent(hunt.hunt_id)}`} />
              <HuntBadges hunt={hunt} />
            </header>
            <div className="grid min-w-0 gap-4 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
              <div className="min-w-0 space-y-1">
                <p className="font-semibold whitespace-pre-wrap break-words">{hunt.hypothesis}</p>
                <p className="text-xs break-words text-muted-foreground">
                  기법: {hunt.techniques.length ? hunt.techniques.join(', ') : '없음'}
                </p>
                <p className="text-xs text-muted-foreground">근거 {hunt.evidence.length}건</p>
              </div>
              <div className="space-y-1 text-xs text-muted-foreground md:min-w-56 md:border-l md:border-border md:pl-4">
                <HuntIncident id={hunt.incident_id} />
                <p>룰 후보: {hunt.rule_candidate ? '예' : '아니오'}</p>
                <p>
                  생성 <Timestamp value={hunt.created_at} />
                </p>
              </div>
            </div>
          </article>
        </li>
      ))}
    </ol>
  );
}
