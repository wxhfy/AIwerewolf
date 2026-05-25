"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  disabled,
  ...props
}: ButtonProps) {
  const baseStyles =
    "inline-flex items-center justify-center rounded-button font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-primary/50";

  const variants = {
    primary:
      "bg-primary text-white hover:bg-primaryHover active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed",
    secondary:
      "bg-cardBackground text-textPrimary border border-border hover:bg-background active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed",
    ghost:
      "bg-transparent text-textPrimary hover:bg-cardBackground active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed",
  };

  const sizes = {
    sm: "h-8 px-3 text-sm",
    md: "h-10 px-4 text-sm",
    lg: "h-12 px-6 text-base",
  };

  return (
    <button
      className={cn(baseStyles, variants[variant], sizes[size], className)}
      disabled={disabled}
      {...props}
    />
  );
}
