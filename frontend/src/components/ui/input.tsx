import type { ComponentProps } from 'react';
import { cn } from '../../lib/utils';

// Local shadcn/ui-style form controls; native elements keep the existing labels and behavior.
const field =
  'mt-1.5 block w-full min-w-0 rounded-md border border-input bg-muted px-3 text-sm text-foreground shadow-xs outline-none transition-colors placeholder:text-faint-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:cursor-not-allowed disabled:opacity-60';

export function Input({ className, ...props }: ComponentProps<'input'>) {
  return <input className={cn(field, 'h-9', className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea className={cn(field, 'min-h-24 resize-y py-2', className)} {...props} />;
}

export function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return <select className={cn(field, 'h-9', className)} {...props} />;
}

export function FieldLabel({ className, ...props }: ComponentProps<'label'>) {
  return (
    <label
      className={cn('block text-xs font-semibold text-muted-foreground', className)}
      {...props}
    />
  );
}
