"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Player } from "@/types";
import { PlayerPortrait } from "@/components/game/PlayerPortrait";

export interface SpeechCardProps {
  player?: Player;
  seat?: number;
  name: string;
  children: React.ReactNode;
  isSpeaking?: boolean;
  headerRight?: React.ReactNode;
  className?: string;
  testId?: string;
  dataEventIds?: string;
}

/** Shared, phase-aware presentation for speech and thinking messages. */
export function SpeechCard({ player, seat, name, children, isSpeaking, headerRight, className, testId, dataEventIds }: SpeechCardProps) {
  const displaySeat = seat ?? player?.seat;
  const displayName = player?.name || name;

  return (
    <div className={cn("py-1", className)} data-testid={testId} data-chat-event-ids={dataEventIds}>
      <div
        className={cn(
          "speech-card flex overflow-hidden rounded-card border border-border bg-cardBackground text-textPrimary shadow-card transition-[border-color,box-shadow] duration-200",
          isSpeaking && "border-primary/40 ring-1 ring-primary/20",
        )}
      >
        {player && (
          <div className="speech-card-portrait shrink-0 bg-primary/5 p-2 sm:p-3">
            <PlayerPortrait player={player} size="md" isHighlighted={isSpeaking} />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 pb-2 pt-3 sm:px-4">
            {displaySeat != null && (
              <span className="speech-card-seat inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
                {displaySeat}
              </span>
            )}
            <span className="speech-card-name min-w-0 break-words text-sm font-semibold text-textPrimary">
              {displayName}
            </span>
            {headerRight && (
              <span className="ml-auto text-xs font-medium text-primary">
                {headerRight}
              </span>
            )}
          </div>
          <div className="speech-card-body whitespace-pre-wrap break-words px-3 pb-3 text-sm leading-7 text-textPrimary sm:px-4 sm:text-base">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
