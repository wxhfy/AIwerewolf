"use client";

import React, { useMemo } from "react";
import { GameEvent, Player, Language } from "@/types";
import { t, tPhase } from "@/lib/i18n";
import { getChatCompletionIds, normalizeSpeechContent } from "@/lib/eventFilter";
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

  const actorId = latestChat?.payload.actor_id || pendingPlayerId || "";
  const player = players.find((item) => item.id === actorId);
  const speakerName = player?.name || latestChat?.payload.actor_name || pendingPlayerName || (language === Language.ZH ? "系统" : "System");
  const speakerSeat = player?.seat;
  const shouldRender = Boolean(latestChat) || Boolean(pendingPlayerName && isDaySpeechPhase(phase));
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
  const completionIds = latestChat ? getChatCompletionIds(latestChat) : [];
  const { displayedText, finished } = useTypewriter(text, {
    enabled: shouldRender && Boolean(latestChat) && !isLocked,
    charsPerSecond: 38,
    maxDurationMs: 9000,
    onComplete: latestChat ? () => completionIds.forEach((id) => onChatComplete?.(id)) : undefined,
  });

  if (!shouldRender) return null;

  const shownText = latestChat ? displayedText || "" : text;
  const isThinking = !latestChat && Boolean(pendingPlayerName);

  return (
    <section
      key={typewriterKey}
      className="relative h-[clamp(6rem,19dvh,9.5rem)] shrink-0 border-t border-border bg-cardBackground px-3 py-2.5 sm:px-4 sm:py-3 [@media(max-height:600px)]:h-24 [@media(max-height:600px)]:py-2"
      data-phase-aware
      data-testid="bottom-dialogue-dock"
      data-chat-event-ids={completionIds.join(",")}
    >
      <div className="mx-auto flex h-full max-w-4xl gap-2.5 sm:gap-3">
        <div
          className={cn(
            "relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-button border border-border bg-primary/5 sm:h-14 sm:w-14",
            latestChat && !finished && "ring-2 ring-primary/25",
          )}
        >
          <span className="font-display text-xl font-semibold text-primary">
            {getPlayerInitial(player, speakerName)}
          </span>
          {speakerSeat != null && (
            <span className="absolute bottom-0.5 right-0.5 rounded bg-primary px-1 py-0.5 text-[10px] font-bold leading-none text-onPrimary">
              {speakerSeat}
            </span>
          )}
        </div>

        <div
          className="flex h-full min-h-0 min-w-0 flex-1 flex-col rounded-button border border-border bg-background/50 px-3 py-2 sm:px-4"
          data-testid="bottom-dialogue-bubble"
        >
          <div className="mb-1.5 flex shrink-0 items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-textPrimary">
                {speakerName}
              </p>
              <p className="text-[11px] text-text-sub">
                {getPhaseHint(latestChat?.phase || phase, language)}
              </p>
            </div>
            <span className="shrink-0 rounded-badge bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
              {isThinking
                ? language === Language.ZH ? "思考中" : "Thinking"
                : !finished && latestChat
                  ? language === Language.ZH ? "发言中" : "Speaking"
                  : language === Language.ZH ? "当前发言" : "Dialogue"}
            </span>
          </div>

          <div
            className="timeline-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain whitespace-pre-wrap break-words pr-1 text-sm leading-relaxed text-textPrimary sm:text-base"
            data-testid="bottom-dialogue-text-wrap"
          >
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
