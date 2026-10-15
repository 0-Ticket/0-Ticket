export function PlainText({ value }: { value: string | null }) {
  return <span className="whitespace-pre-wrap break-words">{value ?? '없음'}</span>;
}
