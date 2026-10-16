import { useRef, useState, type FormEvent } from 'react';
import type { Incident, L2Review } from '../contracts';
import { useIncidentReview } from '../api/incident-queries';
import { badges } from '../lib/display';
import { Button } from './ui/button';
import { FieldLabel, Input, NativeSelect, Textarea } from './ui/input';
import { Choice, FormMessage, ReviewPanel } from './review-form';

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
    <ReviewPanel
      label="L2 검토"
      level="L2"
      description="보고서를 승인하거나 반려 유형과 함께 반려합니다."
    >
      {mutation.isSuccess && (
        <FormMessage tone="success" role="status">
          검토가 저장되었습니다.
        </FormMessage>
      )}
      {refreshFailed && (
        <FormMessage tone="warning">
          최신 상세를 조회하지 못했습니다. 상세 조회를 다시 시도하세요.
        </FormMessage>
      )}
      {closed && <FormMessage tone="neutral">{closed}</FormMessage>}
      {mutation.error && (
        <FormMessage tone="critical" role="alert">
          {mutation.error.message}
        </FormMessage>
      )}
      {validation && (
        <FormMessage tone="critical" role="alert">
          {validation}
        </FormMessage>
      )}
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={unavailable} className="min-w-0 space-y-4">
          <FieldLabel>
            검토자
            <Input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </FieldLabel>
          <fieldset className="min-w-0">
            <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">결정</legend>
            <div className="grid grid-cols-2 gap-2">
              {(['approve', 'reject'] as const).map((value) => (
                <Choice key={value} tone={value === 'approve' ? 'success' : 'critical'}>
                  <input
                    type="radio"
                    name="l2-decision"
                    value={value}
                    checked={decision === value}
                    onChange={() => setDecision(value)}
                    className="accent-[var(--primary)]"
                  />
                  {badges[value].label}
                </Choice>
              ))}
            </div>
          </fieldset>
          {reject && (
            <FieldLabel>
              반려 유형 (필수)
              <NativeSelect
                value={rejectType}
                onChange={(e) => setRejectType(e.target.value as typeof rejectType)}
              >
                <option value="">선택</option>
                {REJECT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {badges[value].label}
                  </option>
                ))}
              </NativeSelect>
            </FieldLabel>
          )}
          <FieldLabel>
            검토 코멘트{reject ? ' (필수)' : ' (선택)'}
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
          </FieldLabel>
          <Button type="submit" className="w-full">
            {mutation.isPending ? '저장 중…' : '검토 제출'}
          </Button>
        </fieldset>
      </form>
    </ReviewPanel>
  );
}
