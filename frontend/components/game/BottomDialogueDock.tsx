"use client";

import React, { useMemo } from "react";
import { GameEvent, Player, Language } from "@/types";
import { t, tPhase } from "@/lib/i18n";
import { normalizeSpeechContent } from "@/lib/eventFilter";
import { useTypewriter } from "@/hooks/useTypewriter";
import { cn } from "@/lib/utils";
import { MentionText } from "@/components/game/MentionText";

interface BottomDialogueDockProps {
  players: Player[];
  currentChat?: GameEvent | null;
  pendingPlayerId?: string;
  pendingPlayerName?: string;
  phase?: string;
  language: Language;
  isLocked?: boolean;
  onChatComplete?: (eventId: string) => void;
}

function getPlayerInitial(player?: Player, fallback?: string) {
  return player?.name?.slice(0, 1) || fallback?.slice(0, 1) || "?";
}

function getPhaseHint(phase: string | undefined, language: Language) {
  if (!phase) return language === Language.ZH ? "等待对局开始" : "Waiting for game";
  return tPhase(phase, language);
}

function isDaySpeechPhase(phase: string | undefined): boolean {
  return Boolean(
    phase === "DAY_BADGE_SPEECH" ||
    phase === "DAY_SPEECH" ||
    phase === "DAY_SHERIFF_CLOSING" ||
    phase === "DAY_PK_SPEECH" ||
    phase === "DAY_LAST_WORDS",
  );
}

export function BottomDialogueDock({
  players,
  currentChat,
  pendingPlayerId,
  pendingPlayerName,
  phase,
  language,
  isLocked,
  onChatComplete,
}: BottomDialogueDockProps) {
  const latestChat = useMemo(() => {
    if (!currentChat) return null;
    return currentChat;
  }, [currentChat]);

  if (!latestChat && !pendingPlayerName) return null;
  if (!latestChat && !isDaySpeechPhase(phase)) return null;

  const actorId = latestChat?.payload.actor_id || pendingPlayerId || "";
  const player = players.find((item) => item.id === actorId);
  const speakerName = player?.name || latestChat?.payload.actor_name || pendingPlayerName || (language === Language.ZH ? "系统" : "System");
  const speakerSeat = player?.seat;
  const text = latestChat
    ? normalizeSpeechContent(latestChat.payload.speech, t("speechPass", language))
    : pendingPlayerName
      ? language === Language.ZH
        ? `${pendingPlayerName} 正在组织语言...`
        : `${pendingPlayerName} is thinking...`
      : language === Language.ZH
        ? "对局记录会在上方展开，当前发言会显示在这里。"
        : "Match log appears above. Current dialogue appears here.";

  const typewriterKey = latestChat?.id || `pending-${pendingPlayerId || phase || "empty"}`;
  const { displayedText, finished } = useTypewriter(text, {
    enabled: Boolean(latestChat) && !isLocked,
    charsPerSecond: 38,
    maxDurationMs: 9000,
    onComplete: latestChat ? () => onChatComplete?.(latestChat.id) : undefined,
  });

  const shownText = latestChat ? displayedText || "" : text;
  const isThinking = !latestChat && Boolean(pendingPlayerName);

  return (
    <section
      key={typewriterKey}
      className="shrink-0 border-t border-border bg-cardBackground/92 px-4 py-3 shadow-[0_-10px_36px_rgba(0,0,0,0.08)] backdrop-blur-xl"
      data-phase-aware
      data-testid="bottom-dialogue-dock"
    >
      <div className="mx-auto flex max-w-5xl gap-3">
        <div
          className={cn(
            "relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border bg-background",
            latestChat && !finished && "ring-2 ring-primary/25",
          )}
        >
          <span className="font-display text-2xl font-bold text-primary">
            {getPlayerInitial(player, speakerName)}
          </span>
          {speakerSeat != null && (
            <span className="absolute bottom-1 right-1 rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-bold leading-none text-white">
              {speakerSeat}
            </span>
          )}
        </div>

        <div className="min-h-[96px] min-w-0 flex-1 rounded-2xl border border-border bg-background/70 px-5 py-4 shadow-card">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate font-display text-base font-bold text-primary">
                {speakerName}
              </p>
              <p className="text-[11px] text-text-sub">
                {getPhaseHint(latestChat?.phase || phase, language)}
              </p>
            </div>
            <span className="shrink-0 text-[11px] text-text-sub/70">
              {isThinking
                ? language === Language.ZH ? "思考中" : "Thinking"
                : !finished && latestChat
                  ? language === Language.ZH ? "发言中" : "Speaking"
                  : language === Language.ZH ? "当前发言" : "Dialogue"}
            </span>
          </div>

          <div className="min-h-[3.4rem] whitespace-pre-wrap break-words text-xl leading-relaxed text-textPrimary">
            <span data-testid="bottom-dialogue-text">
              <MentionText text={shownText} players={players} />
            </span>
            {latestChat && !finished && (
              <span className="ml-1 inline-block h-[1em] w-0.5 animate-pulse align-middle bg-primary" />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
