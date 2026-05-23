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
  // Show the lightweight "思考中" pulse when the engine is waiting on this
  // player's decision (works for both the human seat with pending_input and
  // for AI agents whose turn it currently is in the night sequence).
  isThinking?: boolean;
  // Sheriff (badge holder) — show a gold badge marker.
  isSheriff?: boolean;
  // Currently campaigning for the badge during DAY_BADGE_* phases.
  isBadgeCandidate?: boolean;
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
}: PlayerCardProps) {
  const { viewMode, language } = useAppContext();

  // Reveal-by-default in moderator mode: the user explicitly asked to see all
  // identities + persona intros the moment positions are assigned. We keep the
  // toggle (click hides one) so the "上帝视角" can still be temporarily masked
  // per card, but the *initial* state is fully revealed.
  const [roleRevealed, setRoleRevealed] = useState(true);

  const isDead = !player.alive;
  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;
  const isModerator = viewMode === "moderator";
  // Own role (human seat) always visible — that's allowed disclosure.
  // Moderator view requires explicit click per card.
  const roleVisible = showOwnRole || (isModerator && roleRevealed);

  const containerClass = cn(
    "relative flex flex-col items-center px-3 py-3 rounded-card transition-all duration-200 cursor-pointer select-none",
    "shadow-[0_2px_8px_rgba(0,0,0,0.05),0_1px_2px_rgba(0,0,0,0.03)]",
    "bg-[var(--color-card)]",
    isDead && "opacity-50 grayscale shadow-none",
    isSpeaking && "ring-2 ring-success shadow-[0_4px_20px_rgba(34,197,94,0.30),0_0_0_4px_rgba(34,197,94,0.10)] animate-[pulse_1.6s_ease-in-out_infinite]",
    !isSpeaking && !isDead && "hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,0,0,0.08)]",
    isSelected && "ring-2 ring-primary shadow-[0_4px_16px_rgba(139,90,43,0.2)]",
    isThinking && !isSpeaking && "ring-2 ring-info animate-pulse",
  );

  function handleClick() {
    if (isDead) return;
    // Toggle role reveal in moderator view first, then forward the click.
    if (isModerator) setRoleRevealed((v) => !v);
    onClick?.();
  }

  return (
    <div className={containerClass} onClick={handleClick} role="button" tabIndex={0}>
      {/* Speaking indicator */}
      {isSpeaking && (
        <div className="absolute -top-1.5 -right-1.5">
          <Badge variant="speech" className="text-[10px] px-1.5 py-0">
            &#x1F399;
          </Badge>
        </div>
      )}
      {/* Thinking indicator — only when not also speaking (avoids visual clash) */}
      {isThinking && !isSpeaking && (
        <div className="absolute -top-1.5 -left-1.5">
          <Badge variant="info" className="text-[10px] px-1.5 py-0">
            {language === "zh" ? "思考中" : "Thinking"}
          </Badge>
        </div>
      )}
      {/* Sheriff badge — gold, top-center. Persistent for the whole game once
          awarded; survives BADGE_TRANSFER because the snapshot's holder_id
          updates to the new sheriff. */}
      {isSheriff && (
        <div className="absolute -top-2 left-1/2 -translate-x-1/2">
          <Badge
            className="text-[10px] px-1.5 py-0 font-bold"
            style={{
              background: "linear-gradient(135deg, #FFD700 0%, #FFA500 100%)",
              color: "#5C3A00",
              border: "1px solid #C69200",
              boxShadow: "0 2px 6px rgba(255,165,0,0.35)",
            }}
          >
            {language === "zh" ? "警长" : "Sheriff"}
          </Badge>
        </div>
      )}
      {/* Badge candidate marker — only during DAY_BADGE_SIGNUP/SPEECH/ELECTION.
          Smaller, less attention-grabbing than the sheriff badge. */}
      {isBadgeCandidate && !isSheriff && (
        <div className="absolute -top-2 left-1/2 -translate-x-1/2">
          <Badge
            className="text-[10px] px-1.5 py-0"
            style={{
              background: "rgba(255,215,0,0.18)",
              color: "#8B5A2B",
              border: "1px dashed #C69200",
            }}
          >
            {language === "zh" ? "竞选警长" : "Running"}
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

      {/* Role line — "查看身份" only gates the role itself (狼人/村民/预言家…).
          Persona intro is shown below unconditionally because the user
          considers it part of "进入房间立即可见" rather than a hidden identity. */}
      <div className="w-full mt-0.5">
        {roleVisible && player.role ? (
          <p className={cn("text-xs font-medium leading-tight",
            isWolf ? "text-danger" : isVillage ? "text-success" : "text-text-sub")}>
            {tRole(player.role, language)}
          </p>
        ) : isModerator ? (
          <p className="text-xs text-text-sub/60 leading-tight italic">
            {language === "zh" ? "点击查看身份" : "Tap to reveal"}
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

      {/* Persona intro — always visible when the snapshot carries persona data.
          The user explicitly wants the character profile shown immediately on
          entry; gating it behind the role-reveal toggle was confusing because
          the persona doesn't actually leak alignment, only personality. */}
      {(player as any).persona && (
        <div className="w-full mt-1 space-y-0.5">
          {(player as any).persona.mbti && (
            <p className="text-[10px] text-text-sub leading-tight">
              <span className="font-medium">{(player as any).persona.mbti}</span>
              {(player as any).persona.style_label && (
                <span className="text-text-sub/70"> · {(player as any).persona.style_label}</span>
              )}
            </p>
          )}
          {(player as any).persona.basic_info && (
            <p className="text-[10px] text-text-sub/80 leading-tight line-clamp-2">
              {(player as any).persona.basic_info}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
