import type { ReactNode } from 'react';
import type { Tone } from '../lib/display';
import { cn } from '../lib/utils';

// Visual frame shared by the L1 and L2 forms. Validation and submission stay in each form.
export function ReviewPanel({
  label,
  level,
  description,
  children,
}: {
  label: string;
  level: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="min-w-0 rounded-lg border border-border bg-card p-4 shadow-card"
    >
      <header className="mb-4 flex items-center gap-3 border-b border-border pb-3">
        <span
          aria-hidden="true"
          className="grid size-8 shrink-0 place-items-center rounded-md bg-primary text-xs font-extrabold text-primary-foreground"
        >
          {level}
        </span>
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-tight">{label}</h2>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </header>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

const messageTones: Record<'success' | 'warning' | 'critical' | 'neutral', string> = {
  success: 'border-success/30 bg-success-soft text-success',
  warning: 'border-warning/30 bg-warning-soft text-warning',
  critical: 'border-critical/30 bg-critical-soft text-critical',
  neutral: 'border-border bg-muted text-muted-foreground',
};
export function FormMessage({
  tone,
  role,
  children,
}: {
  tone: keyof typeof messageTones;
  role?: 'status' | 'alert';
  children: ReactNode;
}) {
  return (
    <p
      role={role}
      className={cn(
        'rounded-md border px-3 py-2 text-sm whitespace-pre-wrap break-words',
        messageTones[tone],
      )}
    >
      {children}
    </p>
  );
}

// Radio styled as a selectable card; the label text remains the accessible name.
export function Choice({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold transition-colors hover:bg-muted has-[:disabled]:cursor-not-allowed has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
        tone === 'success' && 'has-[:checked]:border-success has-[:checked]:bg-success-soft',
        tone === 'critical' && 'has-[:checked]:border-critical has-[:checked]:bg-critical-soft',
        tone !== 'success' &&
          tone !== 'critical' &&
          'has-[:checked]:border-primary has-[:checked]:bg-accent',
      )}
    >
      {children}
    </label>
  );
}
