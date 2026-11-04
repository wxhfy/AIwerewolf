"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface VoteTargetGridProps {
  players: Array<{ id: string; name?: string; seat?: number }>;
  selectedId: string;
  onSelect: (id: string) => void;
  disabled?: boolean;
}

export function VoteTargetGrid({ players, selectedId, onSelect, disabled }: VoteTargetGridProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 max-h-[280px] overflow-y-auto py-1">
      {(players || []).map((p) => (
        <button
          key={p.id}
          onClick={() => !disabled && onSelect(p.id)}
          disabled={disabled}
          aria-pressed={selectedId === p.id}
          aria-label={`Vote for ${p.name || p.id}${p.seat ? ` seat ${p.seat}` : ""}`}
          className={cn(
            "flex min-w-0 flex-col items-center p-3 rounded-button border transition-[background-color,border-color,box-shadow,transform] duration-200",
            "enabled:hover:border-primary/40 enabled:active:scale-[0.98] motion-reduce:transform-none",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            selectedId === p.id
              ? "border-accent bg-accent/10 ring-1 ring-accent/30"
              : "border-border bg-background",
          )}
        >
          <span
            className={cn(
              "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mb-1.5",
              selectedId === p.id ? "bg-primary text-onPrimary" : "bg-primary/10 text-primary",
            )}
          >
            {p.seat || "?"}
          </span>
          <span className="break-words text-center text-xs font-medium leading-relaxed text-textPrimary">
            {p.name || p.id}
          </span>
          {selectedId === p.id && (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
              className="text-accent mt-1">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          )}
        </button>
      ))}
    </div>
  );
}
