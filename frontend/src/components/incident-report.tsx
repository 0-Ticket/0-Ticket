import type { IncidentArtifact } from '../contracts';
import { registeredLabel, riskLabels } from '../lib/display';
import { ObjectId, Timestamp } from './contract-display';
import { EvidenceList } from './evidence-list';

// Strings here are LLM output or attacker-controlled values: text nodes only.
export function IncidentReport({ artifact }: { artifact: IncidentArtifact | null }) {
  return (
    <section aria-label="보고서" className="space-y-4 rounded border border-border p-4">
      <h2 className="text-lg font-semibold">보고서</h2>
      {artifact ? (
        <>
          <p>
            생성: <Timestamp value={artifact.generated_at} />
          </p>
          <p
            className={
              artifact.needs_human ? 'rounded bg-accent p-3 font-semibold whitespace-pre-wrap' : ''
            }
          >
            사람 확인 {artifact.needs_human ? '필요' : '불필요'} · {artifact.human_reason ?? '없음'}
          </p>
          <div>
            <h3 className="font-semibold">추정 원인</h3>
            <p className="whitespace-pre-wrap break-words">{artifact.suspected_cause}</p>
          </div>
          <div>
            <h3 className="mb-2 font-semibold">타임라인</h3>
            {artifact.timeline.length ? (
              // The contract guarantees chronological order; keep the response order.
              <ol className="space-y-3 border-l border-border pl-4">
                {artifact.timeline.map((entry, index) => (
                  <li
                    key={index}
                    data-testid="timeline-entry"
                    data-time={entry.time}
                    className="space-y-2"
                  >
                    <Timestamp value={entry.time} />
                    <p className="text-sm">
                      전술 {entry.tactic ?? '없음'} · 기법 {entry.technique ?? '없음'}
                    </p>
                    <p className="whitespace-pre-wrap break-words">{entry.description}</p>
                    <EvidenceList label={`타임라인 근거 ${index + 1}`} evidence={entry.evidence} />
                  </li>
                ))}
              </ol>
            ) : (
              <p>없음</p>
            )}
          </div>
          <div>
            <h3 className="font-semibold">영향 자산</h3>
            {artifact.affected_assets.length ? (
              <ul>
                {artifact.affected_assets.map((asset, index) => (
                  <li key={index} className="break-words">
                    {asset}
                  </li>
                ))}
              </ul>
            ) : (
              <p>없음</p>
            )}
          </div>
          <div>
            <h3 className="font-semibold">IOC</h3>
            {artifact.iocs.length ? (
              <ul className="space-y-1">
                {artifact.iocs.map((ioc, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2 break-all">
                    <span>{registeredLabel(ioc.type)}</span>
                    {/* URLs are copyable text, never links. */}
                    <ObjectId value={ioc.value} />
                  </li>
                ))}
              </ul>
            ) : (
              <p>없음</p>
            )}
          </div>
          <div>
            <h3 className="font-semibold">권고 조치</h3>
            {artifact.recommendations.length ? (
              <ul className="space-y-2">
                {artifact.recommendations.map((item, index) => (
                  <li key={index} className="rounded border border-border p-2">
                    <p className="text-xs font-medium">권고 · 실행하지 않음</p>
                    <p className="whitespace-pre-wrap break-words">{item.action}</p>
                    <p className="text-sm">
                      위험 {riskLabels[item.risk] ?? item.risk} · 되돌릴 수{' '}
                      {item.reversible ? '있음' : '없음'}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>없음</p>
            )}
          </div>
        </>
      ) : (
        <p>없음</p>
      )}
    </section>
  );
}
