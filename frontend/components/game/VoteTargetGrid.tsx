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
            "flex flex-col items-center p-3 rounded-card border-2 transition-all duration-150",
            "hover:-translate-y-0.5 hover:shadow-md",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            selectedId === p.id
              ? "border-accent bg-accent/10 shadow-accent"
              : "border-transparent bg-cardBackground hover:border-border",
          )}
        >
          <span
            className={cn(
              "w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mb-1.5",
              selectedId === p.id ? "bg-accent text-white" : "bg-primary/10 text-primary",
            )}
          >
            {p.seat || "?"}
          </span>
          <span className="text-xs font-medium text-textPrimary text-center leading-tight">
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
