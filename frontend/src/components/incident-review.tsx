import { useRef, useState, type FormEvent } from 'react';
import type { Incident, L2Review } from '../contracts';
import { useIncidentReview } from '../api/incident-queries';
import { badges } from '../lib/display';
import { Button } from './ui/button';
import { FieldLabel, Input, NativeSelect, Textarea } from './ui/input';
import { Choice, FormMessage, ReviewPanel } from './review-form';

const REJECT_TYPES = ['wrong_grouping', 'missing_step', 'wrong_conclusion'] as const;

// C10 review_state is the only signal for an open review opportunity (#21). Review counts,
// C15 rounds and report timestamps are never used to infer it.
const CLOSED_MESSAGES: Record<Exclude<Incident['review_state'], 'awaiting_review'>, string> = {
  analyzing: 'L2 분석 중입니다. 새 검토 기회가 열리면 검토할 수 있습니다.',
  approved: 'L2 검토에서 승인되었습니다.',
  human_handling: '두 번 반려되어 사람이 직접 처리합니다.',
};

export function IncidentReview({
  incident,
  refreshFailed = false,
}: {
  incident: Incident;
  refreshFailed?: boolean;
}) {
  const round = incident.review_state === 'awaiting_review' ? incident.review_round : null;
  // Remember the last opportunity the server opened. A new one remounts the form so the
  // previous answer, message and mutation never carry over; a closed state keeps them.
  const [opened, setOpened] = useState(round);
  if (round !== null && round !== opened) setOpened(round);
  return (
    <IncidentReviewForm
      key={opened ?? 'none'}
      incident={incident}
      round={round}
      refreshFailed={refreshFailed}
    />
  );
}

function IncidentReviewForm({
  incident,
  round,
  refreshFailed,
}: {
  incident: Incident;
  round: number | null;
  refreshFailed: boolean;
}) {
  const [reviewer, setReviewer] = useState('');
  const [decision, setDecision] = useState<L2Review['decision'] | ''>('');
  const [rejectType, setRejectType] = useState<NonNullable<L2Review['reject_type']> | ''>('');
  const [comment, setComment] = useState('');
  const [validation, setValidation] = useState('');
  const locked = useRef(false);
  const mutation = useIncidentReview(incident.incident_id);
  const closed =
    incident.review_state === 'awaiting_review' ? null : CLOSED_MESSAGES[incident.review_state];
  const reject = decision === 'reject';
  // This form instance belongs to one opportunity (keyed above): once answered it stays
  // locked, and only a new server-opened round remounts a fresh form.
  const unavailable = round === null || mutation.isPending || mutation.isSuccess || refreshFailed;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || unavailable || round === null) return;
    if (!reviewer.trim() || !decision || (reject && (!rejectType || !comment.trim()))) {
      setValidation('검토자, 결정을 입력하세요. 반려하면 반려 유형과 코멘트가 필요합니다.');
      return;
    }
    setValidation('');
    locked.current = true;
    try {
      // The received review_round is echoed unchanged as a precondition; the core assigns
      // and records the actual C15 round.
      await mutation.mutateAsync({
        reviewer: reviewer.trim(),
        decision,
        reject_type: reject && rejectType ? rejectType : null,
        comment: comment.trim() || null,
        expected_review_round: round,
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
