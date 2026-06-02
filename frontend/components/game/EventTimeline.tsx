"use client";

import React from "react";
import { EventType, GameEvent, Language, ViewMode } from "@/types";
import { t, tPhase } from "@/lib/i18n";
import { ChatBubble } from "@/components/game/ChatBubble";
import { EventItem } from "@/components/game/EventItem";

interface EventTimelineProps {
  dayBlocks: Array<[number, GameEvent[]]>;
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
  completedIds: Set<string>;
  onChatComplete: (eventId: string) => void;
}

const systemIcons: Partial<Record<EventType, string>> = {
  [EventType.GAME_START]: "\u{1F3AE}",
  [EventType.GAME_END]: "\u{1F3C6}",
  [EventType.SYSTEM_MESSAGE]: "\u{1F4E2}",
};

/**
 * Translate backend English system messages to current language.
 */
function translateSystemMessage(msg: string, lang: Language): string {
  // Only translate in Chinese mode; English messages pass through
  if (lang === "zh") {
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

    // Pattern-based translations
    const nightDeathMatch = msg.match(/^Night deaths?: (.+)\.?$/);
    if (nightDeathMatch) return `昨夜死亡：${nightDeathMatch[1]}。`;

    const badgeCandidates = msg.match(/^Badge signup opens\. Candidates: (.+)\.$/);
    if (badgeCandidates) return `警徽竞选开始，候选人：${badgeCandidates[1]}。`;

    const badgeWinner = msg.match(/^(.+) won the badge election and becomes sheriff\.$/);
    if (badgeWinner) return `${badgeWinner[1]} 赢得警徽竞选，成为警长。`;

    const badgeTransfer = msg.match(/^(.+) 将警徽传给了 (.+)（座位 (\d+)）。$/);
    if (badgeTransfer) return msg; // Already Chinese

    const badgeDestroy = msg.match(/^(.+) 撕掉了警徽.*$/);
    if (badgeDestroy) return msg; // Already Chinese

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

function systemMessage(event: GameEvent, language: Language) {
  if (event.payload.phase) return tPhase(event.payload.phase, language);
  if (/^Night \d+ begins\.$/.test(event.payload.message || "")) return tPhase("NIGHT_START", language);
  if (/^Day \d+ begins\.$/.test(event.payload.message || "")) return tPhase("DAY_START", language);
  const rawMsg = event.payload.message ?? "";
  return translateSystemMessage(rawMsg, language);
}

export function EventTimeline({ dayBlocks, language, viewMode, isHumanMode, humanSeat, completedIds, onChatComplete }: EventTimelineProps) {
  return (
    <>
      {dayBlocks.map(([day, dayEvents]) => (
        <DayEventBlock
          key={day}
          day={day}
          events={dayEvents}
          language={language}
          viewMode={viewMode}
          isHumanMode={isHumanMode}
          humanSeat={humanSeat}
          completedIds={completedIds}
          onChatComplete={onChatComplete}
        />
      ))}
    </>
  );
}

/**
 * Merge consecutive CHAT_MESSAGE events from the same player in the same
 * phase into a single bubble.  Backend emits one event per speech segment;
 * we join them so the UI shows one bubble per speaking turn.
 */
function mergeConsecutiveChats(events: GameEvent[]): GameEvent[] {
  const merged: GameEvent[] = [];
  for (const event of events) {
    const prev = merged[merged.length - 1];
    if (
      prev &&
      event.type === EventType.CHAT_MESSAGE &&
      prev.type === EventType.CHAT_MESSAGE &&
      event.payload.actor_id &&
      event.payload.actor_id === prev.payload.actor_id &&
      event.phase === prev.phase &&
      !(event.payload as any).last_words &&
      !(prev.payload as any).last_words
    ) {
      const prevSpeech = (prev.payload.speech as string) || "";
      const curSpeech = (event.payload.speech as string) || "";
      merged[merged.length - 1] = {
        ...prev,
        payload: {
          ...prev.payload,
          speech: prevSpeech ? `${prevSpeech}\n\n${curSpeech}` : curSpeech,
        },
      };
    } else {
      merged.push(event);
    }
  }
  return merged;
}

function DayEventBlock({
  day,
  events,
  language,
  viewMode,
  isHumanMode,
  humanSeat,
  completedIds,
  onChatComplete,
}: {
  day: number;
  events: GameEvent[];
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
  completedIds: Set<string>;
  onChatComplete: (eventId: string) => void;
}) {
  const rawEvents = events.filter((event) => event.type !== EventType.PRIVATE_INFO && (viewMode === ViewMode.MODERATOR || event.visibility !== "private"));

  // ── Aggregate consecutive multi-segment speeches ──
  const timelineEvents = mergeConsecutiveChats(rawEvents);
  const deaths = rawEvents.filter((event) =>
    event.type === EventType.PLAYER_DIED || event.type === EventType.HUNTER_SHOT || event.type === EventType.WHITE_WOLF_KING_BOOM
  );

  if (timelineEvents.length === 0) return null;

  // ── Reveal index: only CHAT_MESSAGE events gate the queue ──────
  // Non-chat events (system messages, phase changes, vote records)
  // appear together in the gap between chat messages — they don't
  // individually block the queue.  Only uncompleted CHAT_MESSAGE
  // events pause the reveal cursor.
  let revealIndex = timelineEvents.length;
  for (let i = 0; i < timelineEvents.length; i++) {
    if (timelineEvents[i].type === EventType.CHAT_MESSAGE && !completedIds.has(timelineEvents[i].id)) {
      revealIndex = i;
      break;
    }
  }

  const visibleEvents = timelineEvents.slice(0, revealIndex + 1);

  // ── Animating chat: only the first uncompleted bubble animates ──
  let animatingFound = false;
  function shouldAnimateChat(eventId: string): boolean {
    if (animatingFound) return false;
    if (!completedIds.has(eventId)) {
      animatingFound = true;
      return true;
    }
    return false;
  }

  return (
    <div className="mb-5">
      <div className="mb-3 flex items-center gap-3 border-b border-border pb-2">
        <span className="font-display text-2xl font-bold text-primary">D{day}</span>
        {deaths.length > 0 && (
          <span className="truncate text-xs text-danger">
            {deaths.map((death) => death.payload.player_name || death.payload.target_name || "?").join(" · ")} {t("playerDied", language)}
          </span>
        )}
      </div>
      <div className="space-y-0.5">
        {visibleEvents.map((event, index) => (
          <TimelineEvent
            key={event.id || index}
            event={event}
            index={index}
            language={language}
            isHumanMode={isHumanMode}
            humanSeat={humanSeat}
            animateChat={event.type === EventType.CHAT_MESSAGE ? shouldAnimateChat(event.id) : false}
            onChatComplete={onChatComplete}
            isLatest={revealIndex < timelineEvents.length && index === visibleEvents.length - 1 && event.type === EventType.CHAT_MESSAGE && !completedIds.has(event.id)}
          />
        ))}
      </div>
    </div>
  );
}

function TimelineEvent({
  event,
  index,
  language,
  isHumanMode,
  humanSeat,
  animateChat,
  onChatComplete,
  isLatest,
}: {
  event: GameEvent;
  index: number;
  language: Language;
  isHumanMode: boolean;
  humanSeat: number;
  animateChat: boolean;
  onChatComplete: (eventId: string) => void;
  /** True when this is the last visible event and it's an uncompleted chat — shows a typing indicator */
  isLatest?: boolean;
}) {
  const isSystem = event.type === EventType.PHASE_CHANGED || event.type === EventType.GAME_START
    || event.type === EventType.GAME_END || event.type === EventType.SYSTEM_MESSAGE;

  if (isSystem) {
    const msg = systemMessage(event, language);
    const icon = systemIcons[event.type] || "";
    return <ChatBubble speakerName="" content={icon ? `${icon} ${msg}` : msg} isSystem animate={false} />;
  }

  if (event.type === EventType.CHAT_MESSAGE) {
    // Skip empty-content chat bubbles
    const speech = event.payload.speech as string || "";
    if (!speech.trim()) return null;

    return (
      <ChatBubble
        speakerName={event.payload.actor_name || "?"}
        content={speech}
        isOwn={isHumanMode && event.payload.actor_id?.startsWith(`P${humanSeat}-`)}
        phaseLabel={tPhase(event.phase, language)}
        animate={animateChat}
        onTypewriterComplete={() => onChatComplete(event.id)}
      />
    );
  }

  // Non-system, non-chat events (VOTE_CAST, NIGHT_ACTION, etc.)
  // Also respect the reveal: don't show if they're after the reveal point
  return <EventItem event={event} index={index} />;
}
