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
    speech: "bg-accent/15 text-accent animate-breathe",
    seat: "bg-primary text-white font-display text-lg rounded-full w-8 h-8 flex items-center justify-center",
    dead: "bg-text-sub/15 text-text-sub line-through",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-3 py-1 rounded-badge text-xs font-medium",
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
