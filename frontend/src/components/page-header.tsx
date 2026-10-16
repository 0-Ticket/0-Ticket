import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { Icon } from './icon';

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <p className="mb-1 text-[11px] font-bold tracking-[0.14em] text-primary uppercase">
          {eyebrow}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="mt-1 max-w-3xl space-y-0.5 text-sm text-muted-foreground">
          {description}
        </div>
      </div>
      {actions}
    </div>
  );
}

// Static route back to the list screen; the current object ID is plain text.
export function Breadcrumbs({ list, to, current }: { list: string; to: string; current: string }) {
  return (
    <nav aria-label="위치" className="mb-3 flex min-w-0 items-center gap-1.5 text-xs">
      <Link className="text-muted-foreground hover:text-primary" to={to}>
        {list}
      </Link>
      <Icon name="chevron" size={12} className="text-faint-foreground" />
      <span aria-current="page" className="min-w-0 truncate font-mono text-faint-foreground">
        {current}
      </span>
    </nav>
  );
}
