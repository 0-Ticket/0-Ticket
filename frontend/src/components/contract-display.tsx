import { useState } from 'react';
import { Link } from 'react-router';
import { badges, localTime, severityLabels, severityTones } from '../lib/display';
import { cn } from '../lib/utils';
import { Icon } from './icon';
import { Button } from './ui/button';
import { ToneBadge } from './ui/badge';

export function Badge({ value, severity }: { value: string | null; severity?: number }) {
  const style = value !== null && Object.hasOwn(badges, value) ? badges[value] : undefined;
  return (
    <ToneBadge tone={severity === undefined ? style?.tone : (severityTones[severity] ?? 'neutral')}>
      {severity === undefined ? (style?.label ?? value ?? '없음') : severityLabels[severity]}
    </ToneBadge>
  );
}
export function Timestamp({ value }: { value: number }) {
  return (
    <time className="tabular-nums" title={String(value)} dateTime={new Date(value).toISOString()}>
      {localTime(value)}
    </time>
  );
}
export function ObjectId({
  value,
  href,
  className,
}: {
  value: string;
  href?: string;
  className?: string;
}) {
  const [message, setMessage] = useState('');
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setMessage('복사됨');
    } catch {
      setMessage('복사 실패');
    }
  }
  return (
    <span className={cn('inline-flex max-w-full min-w-0 items-center gap-0.5', className)}>
      {href ? (
        <Link
          className="min-w-0 font-mono text-[13px] font-medium break-all text-primary underline-offset-4 hover:underline"
          to={href}
        >
          {value}
        </Link>
      ) : (
        <span className="min-w-0 font-mono text-[13px] break-all">{value}</span>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="size-6"
        aria-label={`${value} 복사`}
        title="복사"
        onClick={() => void copy()}
      >
        <Icon name={message === '복사됨' ? 'check' : 'copy'} size={13} />
      </Button>
      <span role="status" className="text-[11px] text-muted-foreground">
        {message}
      </span>
    </span>
  );
}
export function Extensions({ value }: { value: Record<string, unknown> }) {
  return (
    <details className="group rounded-md border border-border bg-muted text-sm">
      <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-muted-foreground select-none hover:text-foreground">
        확장 필드 ({Object.keys(value).length})
      </summary>
      <div className="border-t border-border px-3 py-2">
        {Object.keys(value).length ? (
          <table className="w-full table-fixed text-left text-xs">
            <tbody>
              {Object.entries(value).map(([key, item]) => (
                <tr key={key} className="border-b border-border last:border-0">
                  <th className="w-2/5 p-1.5 align-top font-mono font-medium break-all text-muted-foreground">
                    {key}
                  </th>
                  <td className="p-1.5 font-mono whitespace-pre-wrap break-all">
                    {item === null
                      ? '없음'
                      : typeof item === 'string'
                        ? item
                        : JSON.stringify(item)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-muted-foreground">없음</p>
        )}
      </div>
    </details>
  );
}
export function QueryError({
  error,
  retry,
  busy = false,
}: {
  error: Error;
  retry: () => void;
  busy?: boolean;
}) {
  return (
    <div
      role="alert"
      className="my-2 flex flex-wrap items-start gap-3 rounded-md border border-critical/30 bg-critical-soft p-3 text-sm"
    >
      <Icon name="alert" className="mt-0.5 text-critical" />
      <p className="min-w-0 flex-1 whitespace-pre-wrap break-words">{error.message}</p>
      <Button variant="outline" size="sm" disabled={busy} onClick={retry}>
        다시 시도
      </Button>
    </div>
  );
}

// Visual wrapper for loading and empty states; the message text itself is unchanged.
export function StatusNote({ children, busy = false }: { children: string; busy?: boolean }) {
  return busy ? (
    <p role="status" className="py-2 text-sm text-muted-foreground">
      {children}
    </p>
  ) : (
    <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
      {children}
    </p>
  );
}
