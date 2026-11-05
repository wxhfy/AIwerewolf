"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "danger" | "warning" | "info" | "phase" | "speech" | "seat" | "dead";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants: Record<string, string> = {
    default: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    danger: "bg-danger/10 text-danger",
    warning: "bg-warning/10 text-warning",
    info: "bg-info/10 text-info",
    phase: "bg-primary/10 text-primary font-display text-sm px-4 py-1.5 rounded-badge",
    speech: "bg-accent/10 text-accent",
    seat: "bg-primary text-onPrimary font-display text-sm rounded-full h-8 min-w-8 justify-center px-1",
    dead: "bg-text-sub/15 text-text-sub line-through",
  };

  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-badge px-2.5 py-1 text-xs font-medium leading-snug",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
