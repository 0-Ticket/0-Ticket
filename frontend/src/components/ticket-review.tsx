import { useRef, useState, type FormEvent } from 'react';
import type { Ticket, HumanReview } from '../contracts';
import { useTicketReview } from '../api/ticket-queries';
import { Button } from './ui/button';
import { FieldLabel, Input, Textarea } from './ui/input';
import { Choice, FormMessage, ReviewPanel } from './review-form';

export function TicketReview({
  ticket,
  refreshFailed = false,
}: {
  ticket: Ticket;
  refreshFailed?: boolean;
}) {
  const [reviewer, setReviewer] = useState('');
  const [decision, setDecision] = useState<HumanReview['decision'] | ''>('');
  const [reason, setReason] = useState('');
  const [validation, setValidation] = useState('');
  const locked = useRef(false);
  const mutation = useTicketReview(ticket.ticket_id);
  const original = ticket.verdict?.verdict;
  const reasonRequired = decision !== '' && decision !== original;
  const unavailable =
    ticket.status !== 'awaiting_human' || mutation.isPending || mutation.isSuccess || refreshFailed;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || unavailable) return;
    if (!reviewer.trim() || !decision || (reasonRequired && !reason.trim())) {
      setValidation('검토자, 판정, 필요한 검토 이유를 입력하세요.');
      return;
    }
    setValidation('');
    locked.current = true;
    try {
      await mutation.mutateAsync({
        reviewer: reviewer.trim(),
        decision,
        reason: reason.trim() || null,
      });
    } catch {
      /* Mutation error is displayed below; never resubmit automatically. */
    } finally {
      locked.current = false;
    }
  }
  return (
    <ReviewPanel
      label="L1 검토"
      level="L1"
      description="에이전트 판정에 동의하거나 TP·FP를 직접 선택합니다."
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
      {ticket.status !== 'awaiting_human' && (
        <FormMessage tone="neutral">현재 검토 대기 상태가 아닙니다.</FormMessage>
      )}
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
          <div className="space-y-1.5">
            <p className="text-xs font-semibold text-muted-foreground">판정</p>
            <div className="grid grid-cols-2 gap-2">
              {(['tp', 'fp'] as const).map((value) => (
                <Choice key={value}>
                  <input
                    type="radio"
                    name="decision"
                    value={value}
                    checked={decision === value}
                    onChange={() => setDecision(value)}
                    className="accent-[var(--primary)]"
                  />
                  {value.toUpperCase()}
                </Choice>
              ))}
            </div>
            {(original === 'tp' || original === 'fp') && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => setDecision(original)}
              >
                동의
              </Button>
            )}
          </div>
          <FieldLabel>
            검토 이유{reasonRequired ? ' (필수)' : ' (선택)'}
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} />
          </FieldLabel>
          <Button type="submit" className="w-full">
            {mutation.isPending ? '저장 중…' : '검토 제출'}
          </Button>
        </fieldset>
      </form>
    </ReviewPanel>
  );
}
