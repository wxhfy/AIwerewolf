"use client";

import React from "react";
import { GameEvent, EventType, Player, Language } from "@/types";
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
  return (
    <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-snug text-text-sub">
      {text}
    </p>
  );
}

function nightCompletionLabel(phase: string, language: Language): string {
  const zh: Record<string, string> = {
    NIGHT_GUARD_ACTION: "守卫",
    NIGHT_WOLF_ACTION: "狼人",
    NIGHT_WITCH_ACTION: "女巫",
    NIGHT_SEER_ACTION: "预言家",
  };
  const en: Record<string, string> = {
    NIGHT_GUARD_ACTION: "Guard",
    NIGHT_WOLF_ACTION: "Wolves",
    NIGHT_WITCH_ACTION: "Witch",
    NIGHT_SEER_ACTION: "Seer",
  };
  return (language === Language.ZH ? zh[phase] : en[phase]) || tPhase(phase, language);
}

function isNightSubphase(phase: string): boolean {
  return phase.startsWith("NIGHT_") && phase !== "NIGHT_START" && phase !== "NIGHT_RESOLVE";
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
      const pName = (p.player_name || p.target_name || "?") as string;
      const player = (players || []).find(pl => pl.id === (p.player_id as string));
      const seatLabel = player != null ? `${player.seat}号 ` : "";
      const reasonText = displayReason
        ? (language === "zh" ? `因${displayReason}出局` : `died by ${displayReason}`)
        : (language === "zh" ? "出局" : "died");
      return (
        <div className="flex justify-center py-2">
          <span className="text-xs text-danger/60 font-medium tracking-wide">
            ◆ {seatLabel}{pName} {reasonText}
          </span>
        </div>
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
      const eventPhase = (p.phase || event.phase || "") as string;
      if (p.message === "行动完毕" || (viewMode !== "moderator" && isNightSubphase(eventPhase))) {
        const phaseText = nightCompletionLabel(eventPhase, language);
        return (
          <span className="text-xs text-text-sub">
            {language === "zh"
              ? `${phaseText}完成任务`
              : `${phaseText} completed`}
          </span>
        );
      }
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

  const hasStrip = ![
    EventType.PLAYER_DIED, EventType.HUNTER_SHOT, EventType.WHITE_WOLF_KING_BOOM,
  ].includes(event.type);

  return (
    <div
      className={cn(
        "flex gap-3 py-2.5 animate-slide-in",
        event.visibility === "private" && "opacity-70"
      )}
      style={{ animationDelay: `${index * 50}ms` }}
    >
      {/* Color strip — hidden for death events (use ◆ prefix instead) */}
      {hasStrip && <div className={cn("w-1 rounded-full flex-shrink-0", strip)} />}

      {/* Content */}
      <div className="flex-1 min-w-0">{content()}</div>
    </div>
  );
}
