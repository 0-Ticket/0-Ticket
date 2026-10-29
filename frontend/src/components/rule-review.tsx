import { useRef, useState, type FormEvent } from 'react';
import type { RuleProposal } from '../contracts';
import { ApiError } from '../api/client';
import { useRuleReview } from '../api/rule-queries';
import type { ErrorCode, RuleReviewInput } from '../api/types';
import { badges } from '../lib/display';
import { Badge } from './contract-display';
import { Button } from './ui/button';
import { FieldLabel, Input } from './ui/input';
import { Choice, FormMessage, ReviewPanel } from './review-form';

// Display rule only: the form opens for the C18 status the server returned as `draft`.
// Whether a review is accepted is decided by the API (`conflict`), not by this screen.
const CLOSED_MESSAGES: Record<string, string> = {
  approved: '승인된 룰 제안입니다. 승인은 SIEM 반영을 뜻하지 않습니다.',
  rejected: '반려된 룰 제안입니다.',
  deployed: '서버가 배포됨 상태로 알려 준 룰 제안입니다.',
};
const ERROR_PREFIX: Record<ErrorCode, string> = {
  invalid_input: '입력 오류',
  conflict: '충돌: 최신 룰 제안을 다시 불러왔습니다.',
  not_found: '룰 제안을 찾을 수 없습니다.',
  internal: '서버 오류',
};

export function RuleReview({
  rule,
  refreshFailed = false,
}: {
  rule: RuleProposal;
  refreshFailed?: boolean;
}) {
  const [reviewer, setReviewer] = useState('');
  const [decision, setDecision] = useState<RuleReviewInput['decision'] | ''>('');
  const [validation, setValidation] = useState('');
  const locked = useRef(false);
  const mutation = useRuleReview(rule.proposal_id);
  const open = rule.status === 'draft';
  const closed = open
    ? null
    : Object.hasOwn(CLOSED_MESSAGES, rule.status)
      ? CLOSED_MESSAGES[rule.status]
      : `알 수 없는 상태(${rule.status})입니다. 검토 폼을 열지 않습니다.`;
  // Once answered, this form stays locked; the refetched C18 decides what is shown next.
  const unavailable = !open || mutation.isPending || mutation.isSuccess || refreshFailed;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || unavailable) return;
    if (!reviewer.trim() || !decision) {
      setValidation('검토자와 결정을 입력하세요.');
      return;
    }
    setValidation('');
    locked.current = true;
    try {
      // The documented request body is exactly reviewer and decision.
      await mutation.mutateAsync({ reviewer: reviewer.trim(), decision });
    } catch {
      /* Mutation error is displayed below; never resubmit automatically. */
    } finally {
      locked.current = false;
    }
  }
  return (
    <ReviewPanel
      label="룰 검토"
      level="R"
      description="룰 제안을 승인하거나 반려합니다. 배포·SIEM 반영은 하지 않습니다."
    >
      {mutation.isSuccess && (
        <FormMessage tone="success" role="status">
          검토가 저장되었습니다. 서버 응답 상태: <Badge value={mutation.data.status} />
        </FormMessage>
      )}
      {refreshFailed && (
        <FormMessage tone="warning">
          최신 룰 제안을 조회하지 못했습니다. 상세 조회를 다시 시도하세요.
        </FormMessage>
      )}
      {closed && <FormMessage tone="neutral">{closed}</FormMessage>}
      {mutation.error && (
        <FormMessage tone="critical" role="alert">
          {mutation.error instanceof ApiError
            ? `${ERROR_PREFIX[mutation.error.code]} ${mutation.error.message}`
            : mutation.error.message}
        </FormMessage>
      )}
      {validation && (
        <FormMessage tone="critical" role="alert">
          {validation}
        </FormMessage>
      )}
      {open && (
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
                      name="rule-decision"
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
            <Button type="submit" className="w-full">
              {mutation.isPending ? '저장 중…' : '검토 제출'}
            </Button>
          </fieldset>
        </form>
      )}
    </ReviewPanel>
  );
}
