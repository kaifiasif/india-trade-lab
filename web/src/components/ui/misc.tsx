import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

export const Progress = ({ value, className }: { value: number; className?: string }) => (
  <ProgressPrimitive.Root className={cn("relative h-2 w-full overflow-hidden rounded-full bg-muted", className)} value={value}>
    <ProgressPrimitive.Indicator className="h-full bg-primary transition-transform duration-500" style={{ transform: `translateX(-${100 - value}%)` }} />
  </ProgressPrimitive.Root>
);

export const Separator = ({ className }: { className?: string }) => <div role="separator" className={cn("h-px w-full bg-border", className)} />;

export const Skeleton = ({ className }: { className?: string }) => <div className={cn("animate-pulse rounded-md bg-muted", className)} />;

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tip({ label, children }: { label: string; children: React.ReactElement }) {
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content sideOffset={6} className="z-50 rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md">
          {label}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? <p className="text-sm text-destructive">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full text-sm", className)} {...props} />
    </div>
  );
}
export const Th = ({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn("h-10 border-b px-3 text-left align-middle text-xs font-medium uppercase tracking-wide text-muted-foreground", className)} {...props} />
);
export const Td = ({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn("border-b px-3 py-2.5 align-middle", className)} {...props} />
);
