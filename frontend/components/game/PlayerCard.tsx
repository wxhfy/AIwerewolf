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
  isSelected?: boolean;
  onClick?: () => void;
  showOwnRole?: boolean;
  wolfTeammates?: string[];
  isThinking?: boolean;
  isSheriff?: boolean;
  isBadgeCandidate?: boolean;
  hasSpoken?: boolean;
  hasVoted?: boolean;
  voteCount?: number;
  /** Name of the player this player voted for */
  voteTargetName?: string;
}

export function PlayerCard({
  player,
  isSpeaking = false,
  isSelected = false,
  onClick,
  showOwnRole = false,
  wolfTeammates,
  isThinking = false,
  isSheriff = false,
  isBadgeCandidate = false,
  hasSpoken = false,
  hasVoted = false,
  voteCount = 0,
  voteTargetName,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();
  const [roleRevealed, setRoleRevealed] = useState(true);
  const isPublic = viewMode !== "moderator";

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;
  const isModerator = viewMode === "moderator";
  const isInteractive = !isDead && (isModerator || Boolean(onClick));
  const persona = player.persona;
  const roleVisible = showOwnRole || (isModerator && roleRevealed);
  const roleLabel = roleVisible && player.role ? tRole(player.role, language) : isModerator ? t("revealRole", language) : t("hiddenRole", language);

  const containerClass = cn(
    "relative flex min-h-[96px] flex-col px-3 py-2.5 rounded-card transition-all duration-200 select-none",
    "bg-cardBackground shadow-sm",
    isInteractive ? "cursor-pointer" : "cursor-default",
    isDead && "opacity-50 grayscale shadow-none",
    isSpeaking && "ring-[3px] ring-success shadow-lg shadow-success/20 animate-[pulse_1s_ease-in-out_infinite] scale-[1.02]",
    !isSpeaking && !isDead && "hover:shadow-lg",
    isSelected && "ring-2 ring-primary shadow-md",
    isThinking && !isSpeaking && "ring-2 ring-info animate-pulse",
  );

  function handleClick() {
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

  return (
    <div
      className={containerClass}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      role={isInteractive ? "button" : undefined}
      tabIndex={isInteractive ? 0 : undefined}
      aria-disabled={isInteractive ? isDead : undefined}
      aria-pressed={isInteractive ? isSelected : undefined}
      aria-label={`${player.seat}. ${player.name}. ${roleLabel}`}
      data-phase-aware
    >
      <div className="flex w-full flex-wrap items-start justify-between gap-2 sm:flex-nowrap">
        <div className="flex min-w-0 items-center gap-2">
          <span className={cn(
            "relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold",
            isDead ? "bg-text-sub/20 text-text-sub" : isSpeaking ? "bg-success text-white" : "bg-primary text-white",
            isSpeaking && "animate-[pulse_0.6s_ease-in-out_infinite]",
          )}>
            {isDead ? "✝" : player.seat}
            {isSpeaking && (
              <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 flex gap-[1px]">
                <span className="w-0.5 h-3 bg-success rounded-full animate-[pulse_0.3s_ease-in-out_infinite]" />
                <span className="w-0.5 h-4 bg-success rounded-full animate-[pulse_0.3s_ease-in-out_infinite_0.15s]" />
                <span className="w-0.5 h-2.5 bg-success rounded-full animate-[pulse_0.3s_ease-in-out_infinite_0.3s]" />
              </span>
            )}
          </span>
          <span className={cn(
            "min-w-0 truncate font-display text-sm font-semibold leading-tight text-textPrimary",
            isDead && "text-text-sub"
          )}>
            {player.name}
          </span>
        </div>

        <div className="flex max-w-full basis-full flex-wrap justify-start gap-1 sm:max-w-[48%] sm:basis-auto sm:justify-end">
          {roleLabel && (
            <Badge
              variant={roleVisible && player.role ? (isWolf ? "danger" : isVillage ? "success" : "default") : "speech"}
              className="whitespace-nowrap px-2 py-0.5 text-[10px] leading-tight"
            >
              {roleLabel}
            </Badge>
          )}
          {isThinking && !isSpeaking && (
            <Badge variant="info" className="whitespace-nowrap px-2 py-0.5 text-[10px] leading-tight">
              {t("playerThinking", language)}
            </Badge>
          )}
          {isSpeaking && (
            <Badge variant="speech" className="whitespace-nowrap px-2 py-0.5 text-[10px] leading-tight">
              {t("playerSpeaking", language)}
            </Badge>
          )}
          {isSheriff && (
            <span className="sheriff-badge inline-flex whitespace-nowrap rounded-badge border px-2 py-0.5 text-[10px] font-bold leading-tight">
              {t("sheriff", language)}
            </span>
          )}
          {isBadgeCandidate && !isSheriff && !isThinking && (
            <span className="inline-flex whitespace-nowrap rounded-badge border border-dashed border-warning bg-warning/15 px-2 py-0.5 text-[10px] leading-tight text-primary">
              {t("badgeRunning", language)}
            </span>
          )}
          {hasSpoken && (
            <span className="inline-flex whitespace-nowrap text-[10px] text-success/70 leading-tight">✓ 已发言</span>
          )}
          {hasVoted && (
            <span className="inline-flex whitespace-nowrap text-[10px] text-accent/70 leading-tight">
              ✓ {voteTargetName ? `已投 → ${voteTargetName}` : "已投票"}
            </span>
          )}
          {voteCount > 0 && (
            <span className="inline-flex whitespace-nowrap rounded-badge bg-accent/15 text-accent px-2 py-0.5 text-[10px] font-bold leading-tight">
              {voteCount}票
            </span>
          )}
        </div>
      </div>

      {showOwnRole && wolfTeammates && wolfTeammates.length > 0 && (
        <p className="mt-1 w-full truncate text-[10px] leading-tight text-text-sub">
          {t("wolfTeam", language)}: {wolfTeammates.join(" · ")}
        </p>
      )}

      {persona && (
        <div className="mt-1.5 w-full space-y-0.5">
          {persona.mbti && (
            <p className="truncate text-[10px] leading-tight text-text-sub">
              <span className="font-medium">{persona.mbti}</span>
              {persona.style_label && (
                <span className="text-text-sub/70"> · {persona.style_label}</span>
              )}
            </p>
          )}
          {persona.basic_info && (
            <p className="line-clamp-2 text-[10px] leading-tight text-text-sub/80">
              {persona.basic_info}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
