import { useState } from 'react';
import { Link } from 'react-router';
import { badges, localTime, severityLabels } from '../lib/display';
import { Button } from './ui/button';

export function Badge({ value, severity }: { value: string | null; severity?: number }) {
  const style = value !== null && Object.hasOwn(badges, value) ? badges[value] : undefined;
  return (
    <span
      className={`inline-block rounded border border-border px-2 py-0.5 text-xs font-medium ${style?.color ?? 'bg-accent'}`}
    >
      {severity === undefined ? (style?.label ?? value ?? '없음') : severityLabels[severity]}
    </span>
  );
}
export function Timestamp({ value }: { value: number }) {
  return (
    <time title={String(value)} dateTime={new Date(value).toISOString()}>
      {localTime(value)}
    </time>
  );
}
export function ObjectId({ value, href }: { value: string; href?: string }) {
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
    <span className="inline-flex flex-wrap items-center gap-2">
      {href ? (
        <Link className="font-mono underline underline-offset-4" to={href}>
          {value}
        </Link>
      ) : (
        <span className="font-mono">{value}</span>
      )}
      <Button variant="outline" aria-label={`${value} 복사`} onClick={() => void copy()}>
        복사
      </Button>
      <span role="status" className="text-xs">
        {message}
      </span>
    </span>
  );
}
export function Extensions({ value }: { value: Record<string, unknown> }) {
  return (
    <details>
      <summary className="cursor-pointer text-sm">확장 필드 ({Object.keys(value).length})</summary>
      {Object.keys(value).length ? (
        <table className="w-full text-left text-xs">
          <tbody>
            {Object.entries(value).map(([key, item]) => (
              <tr key={key}>
                <th className="break-all p-1 align-top">{key}</th>
                <td className="whitespace-pre-wrap break-all p-1">
                  {item === null ? '없음' : typeof item === 'string' ? item : JSON.stringify(item)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p>없음</p>
      )}
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
    <div role="alert" className="my-2 rounded border border-border p-3">
      <p className="whitespace-pre-wrap break-words">{error.message}</p>
      <Button variant="outline" disabled={busy} onClick={retry}>
        다시 시도
      </Button>
    </div>
  );
}
