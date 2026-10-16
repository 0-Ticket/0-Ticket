import { useRef, useState } from 'react';
import type { CaseTask } from '../contracts';
import { ApiError } from '../api/client';
import { useCaseTaskUpdate } from '../api/case-queries';
import type { ErrorCode } from '../api/types';
import { badges } from '../lib/display';
import { Badge, Timestamp } from './contract-display';
import { FormMessage } from './review-form';
import { Section } from './ui/card';
import { NativeSelect } from './ui/input';

// Contract enum values in order. Every value is offered; allowed transitions are the core's.
const TASK_STATUSES: CaseTask['status'][] = ['todo', 'doing', 'done'];
const ERROR_PREFIX: Record<ErrorCode, string> = {
  invalid_input: '입력 오류',
  conflict: '충돌: 최신 Case를 다시 불러왔습니다.',
  not_found: 'Case를 찾을 수 없습니다.',
  internal: '서버 오류',
};

export function CaseTasks({
  caseId,
  tasks,
  refreshFailed = false,
}: {
  caseId: string;
  tasks: CaseTask[];
  refreshFailed?: boolean;
}) {
  const mutation = useCaseTaskUpdate(caseId);
  const [pending, setPending] = useState<{ index: number; status: CaseTask['status'] } | null>(
    null,
  );
  const locked = useRef(false);
  // Pending lasts until the refetch after a save settles, so a stale list is never resent.
  const unavailable = mutation.isPending || refreshFailed;
  async function change(index: number, status: CaseTask['status']) {
    if (locked.current || unavailable) return;
    locked.current = true;
    setPending({ index, status });
    try {
      // The API takes the whole list: only the chosen task's status is replaced.
      await mutation.mutateAsync(
        tasks.map((task, i) => (i === index ? { ...task, status } : task)),
      );
    } catch {
      /* Mutation error is displayed below; never resubmit automatically. */
    } finally {
      locked.current = false;
      setPending(null);
    }
  }
  const error = mutation.error;
  return (
    <Section label="작업" description="상태 변경은 API가 검증하고, 다시 조회한 값을 보여 줍니다.">
      {mutation.isSuccess && (
        <FormMessage tone="success" role="status">
          작업 상태가 저장되었습니다.
        </FormMessage>
      )}
      {refreshFailed && (
        <FormMessage tone="warning">
          최신 Case를 조회하지 못했습니다. 상세 조회를 다시 시도하세요.
        </FormMessage>
      )}
      {error && (
        <FormMessage tone="critical" role="alert">
          {error instanceof ApiError
            ? `${ERROR_PREFIX[error.code]} ${error.message}`
            : `요청 실패 ${error.message}`}
        </FormMessage>
      )}
      {tasks.length ? (
        <ol className="space-y-2">
          {tasks.map((task, index) => (
            <li
              key={index}
              data-testid="case-task"
              className="grid min-w-0 gap-3 rounded-md border border-border bg-muted p-3 sm:grid-cols-[minmax(0,1fr)_10rem]"
            >
              <div className="min-w-0 space-y-1.5">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge value={task.status} />
                  <p className="min-w-0 text-sm font-medium whitespace-pre-wrap break-words">
                    {task.task}
                  </p>
                </div>
                <p className="text-xs whitespace-pre-wrap break-words text-muted-foreground">
                  담당: {task.owner}
                </p>
                <p className="text-xs text-muted-foreground">
                  {task.due_at === null ? (
                    '마감: 없음'
                  ) : (
                    <>
                      마감: <Timestamp value={task.due_at} />
                    </>
                  )}
                </p>
              </div>
              <label className="block min-w-0 text-xs font-semibold text-muted-foreground">
                상태 변경
                <NativeSelect
                  aria-label={`작업 ${index + 1} 상태`}
                  value={pending?.index === index ? pending.status : task.status}
                  disabled={unavailable}
                  onChange={(event) => void change(index, event.target.value as CaseTask['status'])}
                >
                  {TASK_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {badges[value].label}
                    </option>
                  ))}
                </NativeSelect>
              </label>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">없음</p>
      )}
    </Section>
  );
}
