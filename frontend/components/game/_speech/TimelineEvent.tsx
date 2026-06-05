"use client";

import React, { useCallback, useRef } from "react";
import { EventType, GameEvent, Language, Player } from "@/types";
import { t, tPhase, format } from "@/lib/i18n";
import { normalizeSpeechContent } from "@/lib/eventFilter";
import { ChatBubble } from "@/components/game/ChatBubble";
import { EventItem } from "@/components/game/EventItem";

/** Translate backend English system messages to current language. */
function translateSystemMessage(msg: string, lang: Language): string {
  if (lang === Language.ZH) {
    const map: Record<string, string> = {
      "Night 1 begins.": "第一夜开始。",
      "Night 2 begins.": "第二夜开始。",
      "Night 3 begins.": "第三夜开始。",
      "Night 4 begins.": "第四夜开始。",
      "Day 1 begins.": "第一天开始。",
      "Day 2 begins.": "第二天开始。",
      "Day 3 begins.": "第三天开始。",
      "Day 4 begins.": "第四天开始。",
      "No one died last night.": "昨夜是平安夜，无人死亡。",
      "PK vote tied again. No one is eliminated today.": "PK 投票再次平票，今天无人被放逐。",
    };
    if (map[msg]) return map[msg];
    const nightDeath = msg.match(/^Night deaths?: (.+)\.?$/);
    if (nightDeath) return `昨夜死亡：${nightDeath[1]}。`;
    const badgeCandidates = msg.match(/^Badge signup opens\. Candidates: (.+)\.$/);
    if (badgeCandidates) return `警徽竞选开始，候选人：${badgeCandidates[1]}。`;
    const badgeWinner = msg.match(/^(.+) won the badge election and becomes sheriff\.$/);
    if (badgeWinner) return `${badgeWinner[1]} 赢得警徽竞选，成为警长。`;
    const badgeTransfer = msg.match(/^(.+) 将警徽传给了 (.+)（座位 (\d+)）。$/);
    if (badgeTransfer) return msg;
    const badgeDestroy = msg.match(/^(.+) 撕掉了警徽.*$/);
    if (badgeDestroy) return msg;
    const wasVotedOut = msg.match(/^(.+) was voted out\.$/);
    if (wasVotedOut) return `${wasVotedOut[1]} 被投票放逐。`;
    const revealedIdiot = msg.includes("revealed as Idiot");
    if (revealedIdiot) {
      const m = msg.match(/^(.+) revealed as Idiot.*$/);
      if (m) return `${m[1]} 翻开身份为白痴，免于放逐但失去投票权。`;
      return msg;
    }
    const wwkBoom = msg.match(/^(.+) self-destructs as White Wolf King and takes (.+)\.$/);
    if (wwkBoom) return `${wwkBoom[1]} 自爆为白狼王，带走 ${wwkBoom[2]}。`;
    const pkTie = msg.match(/^Vote tie\. PK round between (.+)\.$/);
    if (pkTie) return `投票平局，${pkTie[1]} 进入 PK 环节。`;
  }
  return msg;
}

export interface TimelineEventProps {
  event: GameEvent;
  index: number;
  language: Language;
  isHumanMode: boolean;
  humanSeat: number;
  players?: Player[];
  animateChat: boolean;
  onChatComplete: (eventId: string) => void;
  isLatest?: boolean;
}

function systemMessage(event: GameEvent, language: Language) {
  if (event.payload.phase) return tPhase(event.payload.phase, language);
  if (event.type === EventType.GAME_START) {
    const playerCount = (event.payload as any)?.role_count || (event.payload as any)?.players?.length || 0;
    return language === Language.ZH
      ? `对局开始，${playerCount} 名玩家就位，身份已分配`
      : `Game started, ${playerCount} players ready, roles assigned`;
  }
  if (event.type === EventType.GAME_END) {
    return language === Language.ZH ? "游戏结束" : "Game Over";
  }
  if (/^Night \d+ begins\.$/.test(event.payload.message || "")) return tPhase("NIGHT_START", language);
  if (/^Day \d+ begins\.$/.test(event.payload.message || "")) return tPhase("DAY_START", language);
  const rawMsg = (event.payload.message as string) ?? "";
  return translateSystemMessage(rawMsg, language);
}

export function TimelineEvent({
  event, index, language, isHumanMode, humanSeat,
  players, animateChat, onChatComplete, isLatest,
}: TimelineEventProps) {
  const onChatCompleteRef = useRef(onChatComplete);
  onChatCompleteRef.current = onChatComplete;

  // Pre-compute CHAT_MESSAGE fields at top level (avoid conditional hooks)
  const isChat = event.type === EventType.CHAT_MESSAGE;
  const rawSpeech = isChat ? ((event.payload.speech as string) ?? "") : "";
  const content = isChat ? normalizeSpeechContent(rawSpeech, t("speechPass", language)) : "";
  const hasContent = isChat && rawSpeech.trim().length > 0;
  const actorId = isChat ? (event.payload.actor_id || "") : "";

  // Empty speech: immediately mark as complete
  React.useEffect(() => {
    if (!isChat) return;
    if (rawSpeech.trim()) return;
    onChatCompleteRef.current(event.id);
  }, [event.id, isChat, rawSpeech]);

  // Fallback timer (8s) — always mounted at top level
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  React.useEffect(() => {
    if (!hasContent) return;
    timerRef.current = setTimeout(() => {
      onChatCompleteRef.current(event.id);
    }, 8000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [event.id, hasContent]);

  const handleTypewriterComplete = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    onChatCompleteRef.current(event.id);
  }, [event.id]);

  // ── System messages ──
  const isSystem = event.type === EventType.PHASE_CHANGED
    || event.type === EventType.GAME_START
    || event.type === EventType.GAME_END
    || event.type === EventType.SYSTEM_MESSAGE;

  if (isSystem) {
    const msg = systemMessage(event, language);
    return (
      <ChatBubble
        speakerName=""
        content={msg}
        isSystem
        eventType={event.type}
        eventPhase={event.payload.phase || event.phase || undefined}
        animate={false}
      />
    );
  }

  // ── Chat messages ──
  if (isChat) {
    const player = players?.find(p => p.id === actorId);
    return (
      <ChatBubble
        speakerName={event.payload.actor_name || "?"}
        seat={player?.seat}
        content={content}
        isOwn={isHumanMode && actorId.startsWith(`P${humanSeat}-`)}
        isSpeaking={animateChat && hasContent}
        animate={animateChat && hasContent}
        onTypewriterComplete={hasContent ? handleTypewriterComplete : undefined}
      />
    );
  }

  // ── Vote events: hidden from timeline ──
  if (event.type === EventType.VOTE_CAST) {
    return null;
  }

  // ── Wolf attack NIGHT_ACTION: handled by wolf deliberation panel ──
  if (event.type === EventType.NIGHT_ACTION && event.phase === "NIGHT_WOLF_ACTION") {
    return null;
  }

  // ── Other night actions, player deaths, etc. ──
  return <EventItem event={event} index={index} players={players} />;
}
