import { useState } from "react";
import { Icon } from "../components/icons";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="incident-copy"
      aria-label={`${label} 복사`}
      onClick={() => {
        void Promise.resolve(navigator.clipboard?.writeText(value)).catch(
          () => undefined,
        );
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
    >
      {done ? "복사됨" : "복사"}
    </button>
  );
}

// One <col> per column: a pixel width, or null for the one column that takes what is left (the table layout is fixed).
export function Cols({ widths }: { widths: (number | null)[] }) {
  return (
    <colgroup>
      {widths.map((w, i) => (
        <col key={i} style={w === null ? undefined : { width: w }} />
      ))}
    </colgroup>
  );
}

// Long values stay on one line with an ellipsis; the full text is in the tooltip and the copy button.
export function Clip({ text, label }: { text: string; label: string }) {
  return (
    <span className="incident-clip">
      <span className="clip" title={text}>
        {text}
      </span>
      <CopyButton value={text} label={label} />
    </span>
  );
}

export function SortButton({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: "asc" | "desc";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="incident-sort"
      aria-label={`${label} 정렬`}
      onClick={onClick}
    >
      {label}
      <span aria-hidden="true">
        {active ? (dir === "asc" ? " ▲" : " ▼") : ""}
      </span>
    </button>
  );
}

export function Pager({
  page,
  pages,
  onChange,
}: {
  page: number;
  pages: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="pagination-controls incident-pager">
      <button
        type="button"
        aria-label="이전 페이지"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        <Icon name="left" />
      </button>
      <span aria-live="polite">{`${page} / ${pages}`}</span>
      <button
        type="button"
        aria-label="다음 페이지"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        <Icon name="right" />
      </button>
    </div>
  );
}
