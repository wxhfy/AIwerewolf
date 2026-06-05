"use client";

import React, { useState } from "react";
import { GameEvent, EventType, Player } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase, format } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface EventItemProps {
  event: GameEvent;
  index?: number;
  players?: Player[];
}

const stripColor: Record<string, string> = {
  [EventType.PHASE_CHANGED]: "bg-primary/60",
  [EventType.CHAT_MESSAGE]: "bg-accent/60",
  [EventType.VOTE_CAST]: "bg-accent",
  [EventType.PLAYER_DIED]: "bg-danger/70",
  [EventType.HUNTER_SHOT]: "bg-danger/70",
  [EventType.WHITE_WOLF_KING_BOOM]: "bg-danger/70",
  [EventType.NIGHT_ACTION]: "bg-info/60",
  [EventType.PRIVATE_INFO]: "bg-info/40",
  [EventType.GAME_END]: "bg-accent",
  [EventType.GAME_START]: "bg-primary/40",
  [EventType.SYSTEM_MESSAGE]: "bg-text-sub/40",
};

function VoteReasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const short = text.slice(0, 60);
  const needsToggle = text.length > 80;
  return (
    <p className="text-xs text-text-sub mt-1 leading-snug">
      {open || !needsToggle ? text : `${short}...`}
      {needsToggle && (
        <button onClick={() => setOpen(!open)} className="ml-1 text-primary hover:underline text-[10px]">
          {open ? "收起" : "展开"}
        </button>
      )}
    </p>
  );
}

export function EventItem({ event, index = 0, players = [] }: EventItemProps) {
  const playerById = (id: string) => players.find(p => p.id === id);
  const { language, viewMode } = useAppContext();

  const isPrivate = event.visibility === "private" && viewMode !== "moderator";
  if (isPrivate) return null;

  const strip = stripColor[event.type] || "bg-text-sub/30";

  function content() {
    const p = event.payload;

    if (event.type === EventType.CHAT_MESSAGE) {
      return (
        <span className="text-sm text-textPrimary">
          <span className="font-medium">{p.actor_name}</span>
          <span className="text-text-sub mx-1.5">:</span>
          {p.speech}
        </span>
      );
    }

    if (event.type === EventType.PHASE_CHANGED) {
      return (
        <span className="text-xs text-text-sub italic">
          {format(t("phaseChanged", language), { phase: tPhase(p.phase || event.phase, language) })}
        </span>
      );
    }

    if (event.type === EventType.VOTE_CAST) {
      const isPkVote = (p as any).is_pk_vote;
      const weight = (p as any).vote_weight;
      return (
        <div className={cn(
          "rounded-card border px-3 py-2",
          isPkVote ? "border-warning/30 bg-warning/5" : "border-border/50 bg-cardBackground/50"
        )}>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-textPrimary">{p.voter_name}</span>
            <span className="text-accent text-sm">→</span>
            <span className={cn("text-sm font-semibold", isPkVote ? "text-warning" : "text-primary")}>
              {p.target_name}
            </span>
            {weight && weight > 1 && (
              <span className="text-[10px] bg-accent/15 text-accent px-1.5 py-0.5 rounded-full font-bold">{weight}票</span>
            )}
            {isPkVote && (
              <span className="text-[10px] bg-warning/15 text-warning px-1.5 py-0.5 rounded-full">PK</span>
            )}
          </div>
          {p.reasoning && <VoteReasoning text={p.reasoning as string} />}
        </div>
      );
    }

    if (
      event.type === EventType.PLAYER_DIED ||
      event.type === EventType.HUNTER_SHOT ||
      event.type === EventType.WHITE_WOLF_KING_BOOM
    ) {
      const reasonMap: Record<string, string> = {
        vote: language === "zh" ? "投票放逐" : "voted out",
        wolf: language === "zh" ? "狼人击杀" : "killed by wolf",
        poison: language === "zh" ? "女巫毒杀" : "poisoned",
        hunter: language === "zh" ? "猎人开枪" : "hunter shot",
        boom: language === "zh" ? "白狼王自爆" : "WWK boom",
      };
      const rawReason = (p.reason as string) || "";
      const displayReason = reasonMap[rawReason] || rawReason;
      return (
        <span className="text-sm text-danger font-medium">
          {p.player_name || p.target_name || "?"}
          {language === "zh" ? " 因" : " died by "}
          {displayReason}
          {language === "zh" ? " 出局" : ""}
        </span>
      );
    }

    if (event.type === EventType.GAME_END) {
      return (
        <span className="text-sm font-display font-semibold text-accent">
          {format(t("wins", language), {
            winner: p.winner === "village" ? t("village", language) : t("wolf", language),
            reason: p.reason || "",
          })}
        </span>
      );
    }

    if (event.type === EventType.NIGHT_ACTION) {
      const actionLabels = {
        guard: t("actionGuard", language),
        attack: t("actionAttack", language),
        divine: t("actionDivine", language),
        witch_save: t("actionWitchSave", language),
        witch_poison: t("actionWitchPoison", language),
        skip: t("actionSkip", language),
      } as Record<string, string>;
      const action = actionLabels[p.action_type || ""] || p.action_type || "";
      const rawTarget = (p.target && p.target.name) || p.target_id || "";
      // Resolve player ID → seat+name, fallback to raw value
      const pTarget = typeof rawTarget === "string" ? playerById(rawTarget) : undefined;
      const target = pTarget ? `${pTarget.seat}号 ${pTarget.name}` : rawTarget;
      return (
        <span className="text-xs text-text-sub">
          {format(t("action", language), {
            actor: p.actor_name || "?",
            action,
            target,
            reasoning: p.reasoning || "",
          })}
        </span>
      );
    }

    return (
      <span className="text-xs text-text-sub">
        {p.message || JSON.stringify(p)}
      </span>
    );
  }

  return (
    <div
      className={cn(
        "flex gap-3 py-2.5 animate-slide-in",
        event.visibility === "private" && "opacity-70"
      )}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      {/* Color strip */}
      <div className={cn("w-1 rounded-full flex-shrink-0", strip)} />

      {/* Content */}
      <div className="flex-1 min-w-0">{content()}</div>
    </div>
  );
}
