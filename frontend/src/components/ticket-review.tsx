import { useRef, useState, type FormEvent } from 'react';
import type { Ticket, HumanReview } from '../contracts';
import { useTicketReview } from '../api/ticket-queries';
import { Button } from './ui/button';

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
    <section aria-label="L1 검토" className="space-y-3 rounded border border-border p-4">
      <h2 className="text-lg font-semibold">L1 검토</h2>
      {mutation.isSuccess && <p role="status">검토가 저장되었습니다.</p>}
      {refreshFailed && <p>최신 상세를 조회하지 못했습니다. 상세 조회를 다시 시도하세요.</p>}
      {ticket.status !== 'awaiting_human' && <p>현재 검토 대기 상태가 아닙니다.</p>}
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
            {(original === 'tp' || original === 'fp') && (
              <Button type="button" variant="outline" onClick={() => setDecision(original)}>
                동의
              </Button>
            )}
            {(['tp', 'fp'] as const).map((value) => (
              <label key={value} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="decision"
                  value={value}
                  checked={decision === value}
                  onChange={() => setDecision(value)}
                />
                {value.toUpperCase()}
              </label>
            ))}
          </div>
          <label className="block">
            검토 이유{reasonRequired ? ' (필수)' : ' (선택)'}
            <textarea
              className="mt-1 block w-full rounded border border-input bg-background p-2"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <Button type="submit">{mutation.isPending ? '저장 중…' : '검토 제출'}</Button>
        </fieldset>
      </form>
    </section>
  );
}
