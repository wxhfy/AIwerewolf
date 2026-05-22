"use client";

import React from "react";
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
}

export function PlayerCard({
  player,
  isSpeaking = false,
  isSelected = false,
  onClick,
  showOwnRole = false,
  wolfTeammates,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;

  const containerClass = cn(
    "relative flex flex-col items-center px-3 py-3 rounded-card transition-all duration-200 cursor-pointer select-none",
    "shadow-[0_2px_8px_rgba(0,0,0,0.05),0_1px_2px_rgba(0,0,0,0.03)]",
    "bg-[var(--color-card)]",
    isDead && "opacity-50 grayscale shadow-none",
    isSpeaking && "ring-2 ring-accent shadow-[0_4px_20px_rgba(212,175,55,0.25),0_0_0_4px_rgba(212,175,55,0.08)]",
    !isSpeaking && !isDead && "hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]",
    isSelected && "ring-2 ring-primary shadow-[0_4px_16px_rgba(139,90,43,0.2)]",
  );

  return (
    <div className={containerClass} onClick={onClick} role="button" tabIndex={0}>
      {/* Speaking indicator */}
      {isSpeaking && (
        <div className="absolute -top-1.5 -right-1.5">
          <Badge variant="speech" className="text-[10px] px-1.5 py-0">
            &#x1F399;
          </Badge>
        </div>
      )}

      {/* Seat + name row */}
      <div className="flex items-center gap-2 w-full">
        <span className={cn(
          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold",
          isDead ? "bg-text-sub/20 text-text-sub" : "bg-primary text-white"
        )}>
          {isDead ? "✝" : player.seat}
        </span>
        <span className={cn(
          "font-display text-sm font-semibold text-textPrimary leading-tight truncate",
          isDead && "text-text-sub"
        )}>
          {player.name}
        </span>
      </div>

      {/* Role line */}
      <div className="w-full mt-0.5">
        {(viewMode === "moderator" || showOwnRole) && player.role ? (
          <p className={cn("text-xs font-medium leading-tight",
            isWolf ? "text-danger" : isVillage ? "text-success" : "text-text-sub")}>
            {tRole(player.role, language)}
          </p>
        ) : (
          <p className="text-xs text-text-sub leading-tight">{t("hiddenRole", language)}</p>
        )}
      </div>

      {/* Wolf teammates */}
      {showOwnRole && wolfTeammates && wolfTeammates.length > 0 && (
        <p className="text-[10px] text-text-sub mt-0.5 leading-tight w-full truncate">
          🐺 {wolfTeammates.join(" · ")}
        </p>
      )}
    </div>
  );
}
