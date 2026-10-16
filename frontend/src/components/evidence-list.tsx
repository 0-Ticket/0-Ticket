import { useState } from 'react';
import type { Evidence } from '../contracts';
import { useEvidence } from '../api/ticket-queries';
import { ObjectId, QueryError, Timestamp, Extensions } from './contract-display';
import { Button } from './ui/button';
import { ToneBadge } from './ui/badge';
import { registeredLabel } from '../lib/display';

// Recursive plain text fields, with timestamps and extensions retaining their meaning.
export function ContractFields({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className="grid min-w-0 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[minmax(8rem,auto)_minmax(0,1fr)]">
      {Object.entries(value).map(([key, item]) => (
        <div key={key} className="contents">
          <dt className="font-mono text-xs font-medium break-all text-muted-foreground sm:pt-0.5">
            {key}
          </dt>
          <dd className="min-w-0 whitespace-pre-wrap [overflow-wrap:anywhere]">
            {item === null ? (
              key === 'src_asset' || key === 'dst_asset' ? (
                '자산 정보 없음'
              ) : (
                '없음'
              )
            ) : typeof item === 'number' &&
              /^(time|received_at|created_at|updated_at|first_seen|last_seen|valid_from|valid_to)$/.test(
                key,
              ) ? (
              <Timestamp value={item} />
            ) : key === 'extensions' && typeof item === 'object' && !Array.isArray(item) ? (
              <Extensions value={item as Record<string, unknown>} />
            ) : Array.isArray(item) ? (
              item.length ? (
                <ul className="space-y-1">
                  {item.map((entry, index) => (
                    <li key={index}>
                      {typeof entry === 'string' ? (
                        key.endsWith('_ids') ? (
                          <ObjectId value={entry} />
                        ) : (
                          entry
                        )
                      ) : (
                        JSON.stringify(entry)
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                '없음'
              )
            ) : key === 'unmapped' ? (
              JSON.stringify(item, null, 2)
            ) : typeof item === 'object' ? (
              <ContractFields value={item as Record<string, unknown>} />
            ) : key === 'shared' ? (
              item ? (
                '공용 자산'
              ) : (
                '전용 자산'
              )
            ) : key === 'privileged' ? (
              item ? (
                '관리자 계정'
              ) : (
                '일반 계정'
              )
            ) : (
              String(item)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
function EvidenceItem({ evidence, index }: { evidence: Evidence; index: number }) {
  const [open, setOpen] = useState(false);
  const known = ['alert', 'event', 'raw'].includes(evidence.ref_type);
  const query = useEvidence(evidence.ref_type, evidence.ref_id, open);
  return (
    <li className="flex min-w-0 gap-2.5 rounded-md border border-border bg-card p-2.5">
      <span
        aria-hidden="true"
        className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border border-border-strong text-[10px] text-faint-foreground"
      >
        {index + 1}
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <ToneBadge>{registeredLabel(evidence.ref_type)}</ToneBadge>
          <ObjectId
            value={evidence.ref_id}
            href={
              // Tickets have a documented screen; other unknown types stay as copyable text.
              evidence.ref_type === 'ticket'
                ? `/tickets/${encodeURIComponent(evidence.ref_id)}`
                : undefined
            }
          />
          {known && (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto h-7"
              aria-expanded={open}
              aria-label={`${evidence.ref_id} ${open ? '접기' : '펼치기'}`}
              onClick={() => setOpen(!open)}
            >
              {open ? '접기' : '펼치기'}
            </Button>
          )}
        </div>
        <p className="text-sm whitespace-pre-wrap break-words text-muted-foreground">
          {evidence.note}
        </p>
        {open && (
          <div className="min-w-0 rounded-md border border-border bg-muted p-3">
            {query.isPending && (
              <p role="status" className="text-sm text-muted-foreground">
                근거 불러오는 중…
              </p>
            )}
            {query.error && (
              <QueryError
                error={query.error}
                busy={query.isFetching}
                retry={() => void query.refetch()}
              />
            )}
            {query.data && <ContractFields value={{ ...query.data }} />}
          </div>
        )}
      </div>
    </li>
  );
}
export function EvidenceList({ evidence, label }: { evidence: Evidence[]; label: string }) {
  return (
    <section aria-label={label} className="min-w-0">
      <h3 className="mb-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">
        {label}
      </h3>
      {evidence.length ? (
        <ul className="space-y-2">
          {evidence.map((item, i) => (
            <EvidenceItem key={`${item.ref_type}:${item.ref_id}:${i}`} evidence={item} index={i} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">없음</p>
      )}
    </section>
  );
}
