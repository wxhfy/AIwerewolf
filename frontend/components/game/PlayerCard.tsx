"use client";

import React, { useState } from "react";
import { Player, Alignment } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tRole } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";

interface PlayerCardProps {
  player: Player;
  isSpeaking?: boolean;
  onClick?: () => void;
  showOwnRole?: boolean;
  wolfTeammates?: string[];
  isThinking?: boolean;
  isSheriff?: boolean;
  isBadgeCandidate?: boolean;
  hasSpoken?: boolean;
  /** 夜间角色行动高亮：当前夜间阶段匹配到该玩家角色 */
  isNightActive?: boolean;
  /** 当前游戏阶段（用于区分"发言中"和"行动中"） */
  currentPhase?: string;
  /** Target selection — when true, card is clickable to select as target */
  selectable?: boolean;
  isTarget?: boolean;
  onSelectTarget?: () => void;
}

export function PlayerCard({
  player,
  isSpeaking = false,
  onClick,
  showOwnRole = false,
  wolfTeammates,
  isThinking = false,
  isSheriff = false,
  isBadgeCandidate = false,
  hasSpoken = false,
  isNightActive = false,
  currentPhase,
  selectable = false,
  isTarget = false,
  onSelectTarget,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();
  const [roleRevealed, setRoleRevealed] = useState(true);

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;
  const isModerator = viewMode === "moderator";
  const isInteractive = !isDead && (isModerator || Boolean(onClick));
  const persona = player.persona;
  const roleVisible = showOwnRole || (isModerator && roleRevealed);
  const roleLabel = roleVisible && player.role ? tRole(player.role, language) : isModerator ? t("revealRole", language) : t("hiddenRole", language);

  // ── Container classes ──────────────────────────────────
  // isSpeaking: ring (box-shadow, no layout impact), no scale
  // isThinking: badge in proc area + subtle ring on container
  const containerClass = cn(
    "relative grid min-h-[108px] px-3.5 py-3 rounded-card transition-all duration-300 select-none",
    "bg-cardBackground",
    // 默认显示边框，高亮状态下隐藏默认边框避免和ring混杂
    !(isSpeaking || isThinking || isNightActive || isTarget) && "border border-border/70",
    isInteractive ? "cursor-pointer" : "cursor-default",
    isDead && "opacity-50 grayscale",
    isSpeaking && "ring-[3px] ring-success shadow-lg shadow-success/20 motion-safe:animate-[pulse_1s_ease-in-out_infinite]",
    isThinking && !isSpeaking && "ring-2 ring-info/60 motion-safe:animate-pulse",
    isNightActive && !isSpeaking && !isThinking && "ring-[3px] ring-accent/70 shadow-lg shadow-accent/20 motion-safe:animate-[pulse_1.5s_ease-in-out_infinite]",
    selectable && !isTarget && "cursor-pointer hover:ring-2 hover:ring-accent/50 hover:shadow-md",
    isTarget && "ring-[3px] ring-accent shadow-lg shadow-accent/20",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
  );

  function handleClick() {
    if (selectable && onSelectTarget) { onSelectTarget(); return; }
    if (!isInteractive) return;
    if (isModerator) setRoleRevealed((v) => !v);
    onClick?.();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!isInteractive) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    handleClick();
  }

  // ── Process state badge (bottom-left) ──────────────────
  // 根据阶段类型区分 "发言中" / "行动中" / "投票中"
  const isNightActionPhase = !!(currentPhase && currentPhase.startsWith("NIGHT_"));
  const isVotePhase = !!(currentPhase && (currentPhase.includes("VOTE") || currentPhase.includes("ELECTION")));
  const procLabel: string | null = isSpeaking
    ? (isVotePhase
        ? (language === "zh" ? "投票中" : "Voting")
        : isNightActionPhase
        ? (language === "zh" ? "行动中" : "Acting")
        : t("playerSpeaking", language))
    : isThinking
    ? (isVotePhase
        ? (language === "zh" ? "待投票" : "Pending")
        : t("playerThinking", language))
    : isNightActive
    ? (language === "zh" ? "行动中" : "Acting")
    : (isBadgeCandidate && !isSheriff)
    ? t("badgeRunning", language)
    : null;

  // ── Result state items (bottom-right) ──────────────────
  const resultItems: string[] = [];
  if (isDead) resultItems.push(t("dead", language));
  if (hasSpoken) resultItems.push(language === "zh" ? "已发言" : "Spoken");

  return (
    <div
      className={`${containerClass} player-card-grid`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      aria-disabled={isInteractive ? isDead : undefined}
      aria-pressed={isInteractive ? isTarget : undefined}
      aria-label={`${player.seat}. ${player.name}. ${roleLabel}`}
      data-phase-aware
      data-testid="player-card"
      data-player-id={player.id}
      data-player-seat={player.seat}
      data-selectable={selectable ? "true" : "false"}
    >
      {/* ── Row 1 Left: Identity ─────────────────────────── */}
      <div style={{ gridArea: "identity" }} className="flex min-w-0 items-center gap-2">
        <span className={cn(
          "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-base font-bold",
          isDead ? "bg-text-sub/20 text-text-sub" : isSpeaking ? "bg-success text-white" : "bg-primary text-white",
          isSpeaking && "motion-safe:animate-[pulse_0.6s_ease-in-out_infinite]",
        )}>
          {isDead ? "✝" : player.seat}
          {isSpeaking && (
            <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 flex gap-[1px]">
              <span className="w-0.5 h-3 bg-success rounded-full motion-safe:animate-[pulse_0.3s_ease-in-out_infinite]" />
              <span className="w-0.5 h-4 bg-success rounded-full motion-safe:animate-[pulse_0.3s_ease-in-out_infinite_0.15s]" />
              <span className="w-0.5 h-2.5 bg-success rounded-full motion-safe:animate-[pulse_0.3s_ease-in-out_infinite_0.3s]" />
            </span>
          )}
        </span>
        <span className={cn(
          "min-w-0 truncate font-display font-semibold leading-tight text-textPrimary",
          isDead && "text-text-sub"
        )}>
          {player.name}
        </span>
      </div>

      {/* ── Row 1 Right: Identity Badges ─────────────────── */}
      <div style={{ gridArea: "badges" }} className="flex items-start justify-end gap-1 min-w-[72px] flex-wrap">
        {showOwnRole && (
          <span className="inline-flex text-[11px] bg-primary/20 text-primary px-1.5 py-0.5 rounded-full font-bold shrink-0">
            {language === "zh" ? "我" : "Me"}
          </span>
        )}
        {roleLabel && (
          <Badge
            variant={roleVisible && player.role ? (isWolf ? "danger" : isVillage ? "success" : "default") : "speech"}
            className="whitespace-nowrap px-2 py-0.5 text-[11px] leading-tight"
          >
            {roleLabel}
          </Badge>
        )}
        {isSheriff && (
          <span className="sheriff-badge inline-flex whitespace-nowrap rounded-badge border px-2 py-0.5 text-[11px] font-bold leading-tight">
            {t("sheriff", language)}
          </span>
        )}
      </div>

      {/* ── Row 2: Persona ────────────────────────────────── */}
      <div style={{ gridArea: "persona" }} className="min-h-[1.5em]">
        {persona && (
          <div className="mt-1 w-full space-y-0.5">
            {persona.mbti && (
              <p className="truncate text-[11px] leading-tight text-text-sub">
                <span className="font-medium">{persona.mbti}</span>
                {persona.style_label && (
                  <span className="text-text-sub/70"> · {persona.style_label}</span>
                )}
              </p>
            )}
            {persona.basic_info && (
              <p className="line-clamp-2 text-[11px] leading-tight text-text-sub/80">
                {persona.basic_info}
              </p>
            )}
          </div>
        )}
        {showOwnRole && wolfTeammates && wolfTeammates.length > 0 && (
          <p className="mt-0.5 w-full truncate text-[11px] leading-tight text-text-sub">
            {t("wolfTeam", language)}: {wolfTeammates.join(" · ")}
          </p>
        )}
      </div>

      {/* ── Row 3 Left: Process State ────────────────────── */}
      <div style={{ gridArea: "proc" }} className="flex items-end gap-1 min-h-[22px] flex-wrap">
        {procLabel && (
          <span className={cn(
            "inline-flex whitespace-nowrap rounded-badge px-2 py-0.5 text-[11px] leading-tight transition-opacity duration-200",
            (isSpeaking && isVotePhase) ? "bg-accent/15 text-accent font-medium" :
            isSpeaking ? "bg-success/15 text-success font-medium" :
            isThinking ? "bg-info/15 text-info motion-safe:animate-pulse" :
            isNightActive ? "bg-accent/15 text-accent font-medium motion-safe:animate-pulse" :
            "border border-dashed border-warning bg-warning/15 text-primary"
          )}>
            {procLabel}
          </span>
        )}
      </div>

      {/* ── Row 3 Right: Result State ────────────────────── */}
      <div style={{ gridArea: "result" }} className="flex items-end justify-end gap-1 min-h-[22px] flex-wrap">
        {resultItems.map((item, i) => (
          <span key={i} className="inline-flex whitespace-nowrap text-[11px] text-text-sub/60 leading-tight">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}
