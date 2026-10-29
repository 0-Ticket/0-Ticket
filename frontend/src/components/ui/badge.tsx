import type { ComponentProps } from 'react';
import { cva } from 'class-variance-authority';
import { cn } from '../../lib/utils';
import type { Tone } from '../../lib/display';

// Local shadcn/ui-style badge. Every badge carries text so color is never the only signal.
const tones = cva(
  'inline-flex max-w-full items-center gap-1.5 rounded border px-1.5 py-0.5 text-[11px] leading-4 font-semibold tracking-wide [overflow-wrap:anywhere]',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-inset text-muted-foreground',
        critical: 'border-critical/30 bg-critical-soft text-critical',
        warning: 'border-warning/30 bg-warning-soft text-warning',
        success: 'border-success/30 bg-success-soft text-success',
        info: 'border-info/30 bg-info-soft text-info',
        purple: 'border-purple/30 bg-purple-soft text-purple',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export function ToneBadge({
  tone = 'neutral',
  className,
  ...props
}: ComponentProps<'span'> & { tone?: Tone }) {
  return <span data-tone={tone} className={cn(tones({ tone }), className)} {...props} />;
}
