import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn("animate-pulse-loading rounded-button bg-textSecondary/10", className)} {...props} />;
}

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, icon, children, className }: EmptyStateProps) {
  return (
    <div className={cn("mx-auto flex w-full max-w-md flex-col items-center px-4 py-10 text-center sm:py-14", className)}>
      {icon && <div aria-hidden="true" className="mb-4 flex h-12 w-12 items-center justify-center rounded-card border border-border bg-primary/5 text-primary">{icon}</div>}
      <p className="font-display text-lg font-semibold text-textPrimary">{title}</p>
      {description && <p className="mt-2 max-w-sm text-sm leading-relaxed text-textSecondary">{description}</p>}
      {children && <div className="mt-5 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}
