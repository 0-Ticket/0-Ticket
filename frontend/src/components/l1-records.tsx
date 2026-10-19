import type { ReactNode } from 'react';
import type { BranchResult, Entity, EvidenceRequest, L1DecisionRecord } from '../contracts';
import { registeredLabel, requestTypeLabels } from '../lib/display';
import { Badge, ObjectId, Timestamp } from './contract-display';
import { ContractFields } from './evidence-list';
import { Section } from './ui/card';

const row = 'min-w-0 space-y-1.5 rounded-md border border-border bg-muted p-3 text-sm';
const empty = 'text-sm text-muted-foreground';

// The generated union for C21 `reason` loses the contract's two nullable keys, so read both.
function branchReason(reason: BranchResult['reason']) {
  const value = reason as { rule_id?: string | null; entity?: Entity | null };
  return { ruleId: value.rule_id ?? null, entity: value.entity ?? null };
}

// C21: the path box 25 chose. The screen shows the recorded result and never re-derives it.
export function BranchPath({ branch }: { branch: BranchResult | null }) {
  const reason = branch && branchReason(branch.reason);
  return (
    <Section label="분기 경로" description="엔티티 분기가 고른 경로와 근거">
      {!branch || !reason ? (
        <p className={empty}>분기 기록이 없습니다.</p>
      ) : (
        <div className={row}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge value={branch.path} />
            <ObjectId value={branch.branch_id} />
            <span className="ml-auto text-xs text-faint-foreground">
              <Timestamp value={branch.created_at} />
            </span>
          </div>
          <p className="break-words">규칙: {reason.ruleId ?? '없음'}</p>
          <p className="break-words">
            엔티티:{' '}
            {reason.entity
              ? `${registeredLabel(reason.entity.type)}: ${reason.entity.value}`
              : '없음'}
          </p>
        </div>
      )}
    </Section>
  );
}

// C23: promotions, holds and verdicts, newest first as received. Read-only (box 27).
export function DecisionList({
  decisions,
  label = 'L1 결정',
  description = '승격·보류·판정 기록',
  linkSubjects = false,
  ready = true,
  action,
  children,
}: {
  decisions: L1DecisionRecord[];
  label?: string;
  description?: string;
  linkSubjects?: boolean;
  // False while the list is still loading or failed, so "none" is not claimed too early.
  ready?: boolean;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Section label={label} description={description} action={action}>
      {children}
      {ready && !decisions.length && <p className={empty}>{label}이 없습니다.</p>}
      {decisions.length > 0 && (
        <ol className="space-y-2">
          {decisions.map((decision) => (
            <li key={decision.decision_id} data-decision-id={decision.decision_id} className={row}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge value={decision.decision} />
                {decision.reason !== null && <Badge value={decision.reason} />}
                <ObjectId
                  value={decision.subject_id}
                  href={
                    linkSubjects && decision.subject_type === 'alert'
                      ? `/alerts/${encodeURIComponent(decision.subject_id)}`
                      : linkSubjects && decision.subject_type === 'ticket'
                        ? `/tickets/${encodeURIComponent(decision.subject_id)}`
                        : undefined
                  }
                />
                <span className="ml-auto text-xs text-faint-foreground">
                  <Timestamp value={decision.created_at} />
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                확신도 {decision.confidence === null ? '없음' : decision.confidence}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

// C22: what L1 asked for and what came back. A failed request is the evidence
// collection failure box 27 shows (D-034); the screen does not retry it.
export function EvidenceRequestList({ requests }: { requests: EvidenceRequest[] }) {
  return (
    <Section label="증거 요청" description="큐에 올린 조회와 그 결과">
      {!requests.length && <p className={empty}>증거 요청이 없습니다.</p>}
      {requests.length > 0 && (
        <ol className="space-y-2">
          {requests.map((request) => (
            <li key={request.request_id} data-request-id={request.request_id} className={row}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge value={request.status} />
                <span className="break-words">
                  {requestTypeLabels[request.request_type] ?? request.request_type}
                  {request.domain === null ? '' : ` · ${registeredLabel(request.domain)}`}
                </span>
                <ObjectId value={request.request_id} />
                <span className="ml-auto text-xs text-faint-foreground">
                  <Timestamp value={request.updated_at} />
                </span>
              </div>
              <p className="text-xs text-muted-foreground">재시도 {request.retry_count}회</p>
              {request.failure_reason !== null && (
                <p className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 font-medium break-words">
                  증거 수집 실패: {request.failure_reason}
                </p>
              )}
              <details className="min-w-0 rounded-md border border-border bg-card">
                <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-muted-foreground select-none">
                  요청·결과 상세
                </summary>
                <div className="border-t border-border p-3">
                  <ContractFields value={{ params: request.params, result: request.result }} />
                </div>
              </details>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}
