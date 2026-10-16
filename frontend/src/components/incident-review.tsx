import { useRef, useState, type FormEvent } from 'react';
import type { Incident, L2Review } from '../contracts';
import { useIncidentReview } from '../api/incident-queries';
import { badges } from '../lib/display';
import { Button } from './ui/button';

const REJECT_TYPES = ['wrong_grouping', 'missing_step', 'wrong_conclusion'] as const;

// Only clearly finished states disable the form; the API decides everything else.
function closedMessage(incident: Incident, caseId: string | null) {
  if (caseId !== null) return 'Case가 이미 만들어졌습니다.';
  if (incident.status === 'closed_benign' || incident.status === 'escalated_to_case')
    return '종결된 Incident입니다.';
  return null;
}

export function IncidentReview({
  incident,
  caseId,
  refreshFailed = false,
}: {
  incident: Incident;
  caseId: string | null;
  refreshFailed?: boolean;
}) {
  const [reviewer, setReviewer] = useState('');
  const [decision, setDecision] = useState<L2Review['decision'] | ''>('');
  const [rejectType, setRejectType] = useState<NonNullable<L2Review['reject_type']> | ''>('');
  const [comment, setComment] = useState('');
  const [validation, setValidation] = useState('');
  const locked = useRef(false);
  const mutation = useIncidentReview(incident.incident_id);
  const closed = closedMessage(incident, caseId);
  const reject = decision === 'reject';
  const unavailable = closed !== null || mutation.isPending || mutation.isSuccess || refreshFailed;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || unavailable) return;
    if (!reviewer.trim() || !decision || (reject && (!rejectType || !comment.trim()))) {
      setValidation('검토자, 결정을 입력하세요. 반려하면 반려 유형과 코멘트가 필요합니다.');
      return;
    }
    setValidation('');
    locked.current = true;
    try {
      // `round` is assigned by the core and never sent.
      await mutation.mutateAsync({
        reviewer: reviewer.trim(),
        decision,
        reject_type: reject && rejectType ? rejectType : null,
        comment: comment.trim() || null,
      });
    } catch {
      /* Mutation error is displayed below; never resubmit automatically. */
    } finally {
      locked.current = false;
    }
  }
  return (
    <section aria-label="L2 검토" className="space-y-3 rounded border border-border p-4">
      <h2 className="text-lg font-semibold">L2 검토</h2>
      {mutation.isSuccess && <p role="status">검토가 저장되었습니다.</p>}
      {refreshFailed && <p>최신 상세를 조회하지 못했습니다. 상세 조회를 다시 시도하세요.</p>}
      {closed && <p>{closed}</p>}
      {mutation.error && (
        <p role="alert" className="whitespace-pre-wrap break-words">
          {mutation.error.message}
        </p>
      )}
      {validation && <p role="alert">{validation}</p>}
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={unavailable} className="space-y-3">
          <label className="block">
            검토자
            <input
              className="mt-1 block w-full rounded border border-input bg-background p-2"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </label>
          <div className="flex flex-wrap items-center gap-4">
            {(['approve', 'reject'] as const).map((value) => (
              <label key={value} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="l2-decision"
                  value={value}
                  checked={decision === value}
                  onChange={() => setDecision(value)}
                />
                {badges[value].label}
              </label>
            ))}
          </div>
          {reject && (
            <label className="block">
              반려 유형 (필수)
              <select
                className="mt-1 block w-full rounded border border-input bg-background p-2"
                value={rejectType}
                onChange={(e) => setRejectType(e.target.value as typeof rejectType)}
              >
                <option value="">선택</option>
                {REJECT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {badges[value].label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="block">
            검토 코멘트{reject ? ' (필수)' : ' (선택)'}
            <textarea
              className="mt-1 block w-full rounded border border-input bg-background p-2"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <Button type="submit">{mutation.isPending ? '저장 중…' : '검토 제출'}</Button>
        </fieldset>
      </form>
    </section>
  );
}
