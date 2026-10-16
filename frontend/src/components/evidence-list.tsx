import { useState } from 'react';
import type { Evidence } from '../contracts';
import { useEvidence } from '../api/ticket-queries';
import { ObjectId, QueryError, Timestamp, Extensions } from './contract-display';
import { Button } from './ui/button';
import { registeredLabel } from '../lib/display';

// Recursive plain text fields, with timestamps and extensions retaining their meaning.
export function ContractFields({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className="grid gap-2 text-sm sm:grid-cols-[minmax(8rem,auto)_1fr]">
      {Object.entries(value).map(([key, item]) => (
        <div key={key} className="contents">
          <dt className="font-medium break-all">{key}</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words">
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
function EvidenceItem({ evidence }: { evidence: Evidence }) {
  const [open, setOpen] = useState(false);
  const known = ['alert', 'event', 'raw'].includes(evidence.ref_type);
  const query = useEvidence(evidence.ref_type, evidence.ref_id, open);
  return (
    <li className="space-y-2 rounded border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span>{registeredLabel(evidence.ref_type)}</span>
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
            aria-expanded={open}
            aria-label={`${evidence.ref_id} ${open ? '접기' : '펼치기'}`}
            onClick={() => setOpen(!open)}
          >
            {open ? '접기' : '펼치기'}
          </Button>
        )}
      </div>
      <p className="whitespace-pre-wrap break-words">{evidence.note}</p>
      {open && (
        <div>
          {query.isPending && <p role="status">근거 불러오는 중…</p>}
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
    </li>
  );
}
export function EvidenceList({ evidence, label }: { evidence: Evidence[]; label: string }) {
  return (
    <section aria-label={label}>
      <h3 className="mb-2 font-semibold">{label}</h3>
      {evidence.length ? (
        <ul className="space-y-2">
          {evidence.map((item, i) => (
            <EvidenceItem key={`${item.ref_type}:${item.ref_id}:${i}`} evidence={item} />
          ))}
        </ul>
      ) : (
        <p>없음</p>
      )}
    </section>
  );
}
