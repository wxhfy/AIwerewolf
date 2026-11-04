"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  disabled,
  loading = false,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  const baseStyles =
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-button font-medium leading-snug transition-[background-color,border-color,color,box-shadow,transform,opacity] duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 enabled:active:scale-[0.98] motion-reduce:transform-none";

  const variants = {
    primary:
      "border border-transparent bg-primary text-onPrimary enabled:hover:bg-primaryHover",
    secondary:
      "bg-cardBackground text-textPrimary border border-border enabled:hover:border-primary/40 enabled:hover:bg-primary/5",
    ghost:
      "border border-transparent bg-transparent text-textSecondary enabled:hover:bg-primary/10 enabled:hover:text-textPrimary",
  };

  const sizes = {
    sm: "min-h-9 px-3 py-1.5 text-xs sm:text-sm",
    md: "min-h-11 px-4 py-2 text-sm",
    lg: "min-h-12 px-6 py-3 text-base",
  };

  return (
    <button
      className={cn(baseStyles, variants[variant], sizes[size], className)}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <span aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent" />}
      {children}
    </button>
  );
}
