"use client";

import React from "react";
import { GameEvent, EventType } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase, format } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";

interface EventItemProps {
  event: GameEvent;
}

export function EventItem({ event }: EventItemProps) {
  const { language } = useAppContext();

  function getEventContent() {
    const payload = event.payload;

    if (payload.message) {
      return payload.message;
    }

    if (event.type === EventType.CHAT_MESSAGE) {
      return `${payload.actor_name}: ${payload.speech}`;
    }

    if (event.type === EventType.VOTE_CAST) {
      return format(t("voted", language), {
        voter: payload.voter_name,
        target: payload.target_name,
        reasoning: payload.reasoning || "",
      });
    }

    if (event.type === EventType.PLAYER_DIED) {
      return format(t("died", language), {
        player: payload.player_name,
        reason: payload.reason,
      });
    }

    if (event.type === EventType.GAME_END) {
      return format(t("wins", language), {
        winner: payload.winner === "village" ? t("village", language) : t("wolf", language),
        reason: payload.reason,
      });
    }

    if (event.type === EventType.NIGHT_ACTION) {
      const target = payload.target ? payload.target.name : payload.target_id || t("none", language);
      return format(t("action", language), {
        actor: payload.actor_name,
        action: payload.action_type,
        target,
        reasoning: payload.reasoning || "",
      });
    }

    if (event.type === EventType.PHASE_CHANGED) {
      return format(t("phaseChanged", language), {
        phase: tPhase(payload.phase, language),
      });
    }

    return JSON.stringify(payload);
  }

  const isPrivate = event.visibility === "private";

  return (
    <div className="flex gap-3 py-3 border-b border-border last:border-b-0">
      <div className="flex flex-col items-center">
        <Badge variant="default">{`D${event.day}`}</Badge>
        <span className="mt-1 text-xs text-textSecondary">{tPhase(event.phase, language)}</span>
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-textPrimary">{event.type}</span>
          {isPrivate && <Badge variant="warning">{t("privateTag", language)}</Badge>}
        </div>
        <p className="mt-1 text-sm text-textSecondary">{getEventContent()}</p>
      </div>
    </div>
  );
}
