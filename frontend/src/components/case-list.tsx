import type { Case } from '../contracts';
import { badges, toneRails } from '../lib/display';
import { cn } from '../lib/utils';
import { Badge, ObjectId, Timestamp } from './contract-display';

// Display-only counts of the received tasks. They never decide Case status, progress,
// completion or priority.
const TASK_STATUSES = ['todo', 'doing', 'done'] as const;

export function CaseList({ cases }: { cases: Case[] }) {
  return (
    <ol className="space-y-3">
      {cases.map((item) => {
        const owners = [...new Set(item.tasks.map((task) => task.owner))];
        const tone = Object.hasOwn(badges, item.status) ? badges[item.status].tone : 'neutral';
        return (
          <li key={item.case_id}>
            <article
              className={cn(
                'min-w-0 overflow-hidden rounded-lg border border-l-4 border-border bg-card shadow-card',
                toneRails[tone],
              )}
            >
              <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-2.5">
                <ObjectId
                  value={item.case_id}
                  href={`/cases/${encodeURIComponent(item.case_id)}`}
                />
                <Badge value={item.status} />
              </header>
              <div className="grid min-w-0 gap-4 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0 space-y-1">
                  <p className="font-semibold whitespace-pre-wrap break-words">{item.title}</p>
                  <p className="flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
                    Incident{' '}
                    <ObjectId
                      value={item.incident_id}
                      href={`/incidents/${encodeURIComponent(item.incident_id)}`}
                    />
                  </p>
                  <p className="text-xs whitespace-pre-wrap break-words text-muted-foreground">
                    담당: {owners.length ? owners.join(', ') : '없음'}
                  </p>
                </div>
                <div className="space-y-1 text-xs text-muted-foreground md:min-w-56 md:border-l md:border-border md:pl-4">
                  <p className="text-sm font-semibold text-foreground">
                    작업 {item.tasks.length}건
                  </p>
                  <p>
                    {TASK_STATUSES.map(
                      (status) =>
                        `${badges[status].label} ${item.tasks.filter((task) => task.status === status).length}`,
                    ).join(' · ')}
                  </p>
                  <p>
                    생성 <Timestamp value={item.created_at} />
                  </p>
                  <p>
                    {item.closed_at === null ? (
                      '종결: 없음'
                    ) : (
                      <>
                        종결 <Timestamp value={item.closed_at} />
                      </>
                    )}
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
