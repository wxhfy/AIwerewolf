"use client";

import React from "react";
import { GameEvent, EventType } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, format } from "@/lib/i18n";
import { EventItem } from "@/components/game/EventItem";

interface DayBlockProps {
  day: number;
  events: GameEvent[];
}

export function DayBlock({ day, events }: DayBlockProps) {
  const { language } = useAppContext();

  // Find death events for the day header
  const deaths = events.filter(
    (e) =>
      e.type === EventType.PLAYER_DIED ||
      e.type === EventType.HUNTER_SHOT ||
      e.type === EventType.WHITE_WOLF_KING_BOOM
  );

  const deathLine =
    deaths.length > 0
      ? deaths
          .map((d) =>
            format(t("died", language), {
              player: d.payload.player_name || d.payload.target_name || "?",
              reason: d.payload.reason || d.type.toLowerCase(),
            })
          )
          .join(" · ")
      : null;

  return (
    <div className="mb-6">
      {/* Day header */}
      <div className="flex items-center gap-3 mb-3 pb-2 border-b border-border">
        <span className="font-display text-lg font-bold text-primary">
          D{day}
        </span>
        {deathLine && (
          <span className="text-xs text-danger truncate">{deathLine}</span>
        )}
      </div>

      {/* Event list */}
      <div className="space-y-1">
        {events.map((event, index) => (
          <EventItem key={event.id || index} event={event} index={index} />
        ))}
      </div>
    </div>
  );
}
