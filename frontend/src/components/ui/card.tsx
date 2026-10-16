import type { ComponentProps, ReactNode } from 'react';
import { cn } from '../../lib/utils';

// Local shadcn/ui-style card surfaces shared by list rows and detail sections.
export function Card({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'min-w-0 rounded-lg border border-border bg-card text-card-foreground shadow-card',
        className,
      )}
      {...props}
    />
  );
}

// A labelled region: the accessible name stays the section label used by the screen rules.
export function Section({
  label,
  title = label,
  description,
  action,
  className,
  bodyClassName,
  children,
}: {
  label: string;
  title?: ReactNode;
  description?: string;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        'min-w-0 overflow-hidden rounded-lg border border-border bg-card shadow-card',
        className,
      )}
    >
      <header className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
          {description && <p className="text-xs text-muted-foreground">{description}</p>}
        </div>
        {action}
      </header>
      <div className={cn('space-y-4 p-4', bodyClassName)}>{children}</div>
    </section>
  );
}

export function MetaLabel({ children }: { children: ReactNode }) {
  return (
    <span className="mb-1 block text-[11px] font-semibold tracking-wider text-faint-foreground uppercase">
      {children}
    </span>
  );
}
