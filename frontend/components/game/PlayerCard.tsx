"use client";

import React, { useState } from "react";
import { Player, Alignment } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tRole } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { PlayerPortrait } from "@/components/game/PlayerPortrait";

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
  compact?: boolean;
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
  compact = false,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();
  const [roleRevealed, setRoleRevealed] = useState(true);

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;
  const isModerator = viewMode === "moderator";
  const isInteractive = !isDead && (isModerator || Boolean(onClick));
  const isClickable = selectable || isInteractive;
  const persona = player.persona;
  const roleVisible = showOwnRole || (isModerator && roleRevealed);
  const roleLabel = roleVisible && player.role ? tRole(player.role, language) : isModerator ? t("revealRole", language) : t("hiddenRole", language);

  // ── Container classes ──────────────────────────────────
  // isSpeaking: ring (box-shadow, no layout impact), no scale
  // isThinking: badge in proc area + subtle ring on container
  const containerClass = cn(
    "relative grid rounded-card border select-none transition-[background-color,border-color,box-shadow,opacity] duration-200",
    compact ? "min-h-[96px] gap-x-2 px-2.5 py-2 [@media(max-height:500px)]:min-h-16 [@media(max-height:500px)]:py-1.5" : "min-h-[120px] px-3 py-3",
    "bg-cardBackground",
    // 默认显示边框，高亮状态下隐藏默认边框避免和ring混杂
    "border-border",
    isClickable ? "cursor-pointer hover:border-primary/40" : "cursor-default",
    isDead && "opacity-70 grayscale",
    isSpeaking && "border-success/50 ring-1 ring-success/30",
    isThinking && !isSpeaking && "border-info/50 ring-1 ring-info/20",
    isNightActive && !isSpeaking && !isThinking && "border-accent/50 ring-1 ring-accent/20",
    selectable && !isTarget && "cursor-pointer hover:ring-2 hover:ring-accent/50 hover:shadow-md",
    isTarget && "border-accent ring-2 ring-accent/60 bg-accent/5",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
  );

  function handleClick() {
    if (selectable && onSelectTarget) { onSelectTarget(); return; }
    if (!isClickable) return;
    if (isModerator) setRoleRevealed((v) => !v);
    onClick?.();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!isClickable) return;
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
      role={isClickable ? "button" : undefined}
      tabIndex={isClickable ? 0 : undefined}
      aria-pressed={selectable ? isTarget : undefined}
      aria-label={`${player.seat}. ${player.name}. ${roleLabel}`}
      data-phase-aware
      data-testid="player-card"
      data-player-id={player.id}
      data-player-seat={player.seat}
      data-selectable={selectable ? "true" : "false"}
    >
      {/* ── Portrait ─────────────────────────────────────── */}
      <div style={{ gridArea: "portrait" }} className="flex items-start">
        <div className="relative">
          <PlayerPortrait player={player} size="sm" isHighlighted={isSpeaking || isNightActive || isTarget} className={compact ? "h-10 w-10 rounded-button [@media(max-height:500px)]:h-8 [@media(max-height:500px)]:w-8" : "h-12 w-12 rounded-button"} />
          <span className={cn(
            "absolute -bottom-1 -right-1 flex h-6 min-w-6 items-center justify-center rounded-full border-2 border-cardBackground px-1 text-[11px] font-bold leading-none shadow-sm",
            isDead ? "bg-cardBackground text-textSecondary" : "bg-primary text-onPrimary",
          )}>
            {isDead ? "✝" : player.seat}
          </span>
        </div>
      </div>

      {/* ── Row 1 Left: Identity ─────────────────────────── */}
      <div style={{ gridArea: "identity" }} className="flex min-w-0 items-center gap-2">
        <span className={cn(
          "min-w-0 truncate font-display font-semibold leading-snug text-textPrimary",
          compact && "text-sm",
          isDead && "text-text-sub"
        )}>
          {player.name}
        </span>
      </div>

      {/* ── Row 1 Right: Identity Badges ─────────────────── */}
      <div style={{ gridArea: "badges" }} className="flex min-w-0 flex-wrap items-center gap-1 pt-1">
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
      <div style={{ gridArea: "persona" }} className={compact ? "hidden" : "mt-2 min-w-0"}>
        {persona && (
          <div className="mt-1 w-full space-y-0.5">
            {persona.mbti && (
              <p className="truncate text-[11px] leading-tight text-text-sub">
                <span className="font-medium">{persona.mbti}</span>
                {persona.style_label && (
                  <span> · {persona.style_label}</span>
                )}
              </p>
            )}
            {persona.basic_info && (
              <p className="line-clamp-2 text-xs leading-relaxed text-text-sub">
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
      <div style={{ gridArea: "proc" }} className={cn("flex min-h-[20px] flex-wrap items-end gap-1 pt-1", compact && "[@media(max-height:500px)]:hidden")}>
        {procLabel && (
          <span className={cn(
            "inline-flex whitespace-nowrap rounded-badge px-2 py-0.5 text-[11px] leading-tight transition-opacity duration-200",
            (isSpeaking && isVotePhase) ? "bg-accent/15 text-accent font-medium" :
            isSpeaking ? "bg-success/15 text-success font-medium" :
            isThinking ? "bg-info/15 text-info" :
            isNightActive ? "bg-accent/15 text-accent font-medium" :
            "border border-dashed border-warning bg-warning/15 text-primary"
          )}>
            {procLabel}
          </span>
        )}
      </div>

      {/* ── Row 3 Right: Result State ────────────────────── */}
      <div style={{ gridArea: "result" }} className={cn("flex items-end justify-end gap-1 min-h-[22px] flex-wrap", compact && "[@media(max-height:500px)]:hidden")}>
        {resultItems.map((item, i) => (
          <span key={i} className="inline-flex whitespace-nowrap text-[11px] text-text-sub leading-tight">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}
