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
}

export function PlayerCard({
  player,
  isSpeaking = false,
  isSelected = false,
  onClick,
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;

  const containerClass = cn(
    "relative flex flex-col items-center p-4 rounded-card transition-all duration-200 cursor-pointer select-none",
    // Floating effect — layered shadows for depth
    "shadow-[0_4px_16px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)]",
    "bg-[var(--color-card)]",
    isDead && "opacity-50 grayscale shadow-none",
    isSpeaking && "ring-2 ring-accent shadow-[0_4px_20px_rgba(212,175,55,0.25),0_0_0_4px_rgba(212,175,55,0.08)]",
    !isSpeaking && !isDead && "hover:-translate-y-1 hover:shadow-[0_12px_32px_rgba(0,0,0,0.10),0_2px_6px_rgba(0,0,0,0.06)]",
    isSelected && "ring-2 ring-primary shadow-[0_4px_16px_rgba(139,90,43,0.2)]",
  );

  return (
    <div className={containerClass} onClick={onClick} role="button" tabIndex={0}>
      {/* Speaking indicator */}
      {isSpeaking && (
        <div className="absolute -top-2 -right-2">
          <Badge variant="speech" className="text-xs px-2 py-0.5">
            &#x1F399;
          </Badge>
        </div>
      )}

      {/* Seat number — large editorial number */}
      <Badge variant={isDead ? "dead" : "seat"} className="mb-2">
        {isDead ? "✝" : player.seat}
      </Badge>

      {/* Name */}
      <p
        className={cn(
          "font-display text-sm font-semibold text-textPrimary text-center leading-tight",
          isDead && "text-text-sub"
        )}
      >
        {player.name}
      </p>

      {/* Role / hidden */}
      <div className="mt-1.5 text-center min-h-[20px]">
        {viewMode === "moderator" && player.role ? (
          <p
            className={cn(
              "text-xs font-medium",
              isWolf ? "text-danger" : isVillage ? "text-success" : "text-text-sub"
            )}
          >
            {tRole(player.role, language)}
          </p>
        ) : (
          <p className="text-xs text-text-sub">{t("hiddenRole", language)}</p>
        )}
      </div>

      {/* Persona label (if available) */}
      {player.persona?.style_label && (
        <p className="mt-1 text-[10px] text-text-sub italic truncate max-w-full">
          {player.persona.style_label}
        </p>
      )}

      {/* Status tag */}
      <div className="mt-2">
        {isDead ? (
          <Badge variant="dead" className="text-[10px] px-2 py-0">
            {t("dead", language)}
          </Badge>
        ) : (
          <Badge variant="success" className="text-[10px] px-2 py-0">
            {t("alive", language)}
          </Badge>
        )}
      </div>
    </div>
  );
}
