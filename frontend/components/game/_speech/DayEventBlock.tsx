"use client";

import React, { useEffect, useRef } from "react";
import { EventType, GameEvent, Language, ViewMode, Player } from "@/types";
import { t } from "@/lib/i18n";
import { TimelineEvent } from "./TimelineEvent";
import { ChatBubble } from "@/components/game/ChatBubble";
import { VoteResultPanel } from "@/components/game/VoteResultPanel";

// ── Types ────────────────────────────────────────────────────────────

export interface DayEventBlockProps {
  day: number;
  events: GameEvent[];
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
  completedIds: Set<string>;
  onChatComplete: (eventId: string) => void;
  hideDayHeaders?: boolean;
  dayVotes?: Record<string, string>;
  players?: Player[];
  isTransitioning?: boolean;
  currentDay?: number;
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
}

// ── Helpers ──────────────────────────────────────────────────────────

function isRedundantPhaseAnnouncement(event: GameEvent): boolean {
  if (event.type === EventType.SYSTEM_MESSAGE) {
    const msg = event.payload.message || "";
    return /^Night \d+ begins\.$/.test(msg)
        || /^Day \d+ begins\.$/.test(msg)
        || /was voted out\.$/.test(msg);  // elimination confirmed after last words
  }
  if (event.type === EventType.PHASE_CHANGED && event.payload.phase === "GAME_END") {
    return true;
  }
  return false;
}

function mergeConsecutiveChats(events: GameEvent[]): GameEvent[] {
  const merged: GameEvent[] = [];
  for (const event of events) {
    const prev = merged[merged.length - 1];
    // Don't merge multi-segment speeches (segment_total > 1) — they are
    // intentionally separate bubbles from the backend
    const isMultiSegment = (event.payload as any)?.segment_total > 1
      || (prev?.payload as any)?.segment_total > 1;
    if (
      !isMultiSegment &&
      prev && event.type === EventType.CHAT_MESSAGE && prev.type === EventType.CHAT_MESSAGE &&
      event.payload.actor_id && event.payload.actor_id === prev.payload.actor_id &&
      event.phase === prev.phase &&
      !(event.payload as any).last_words && !(prev.payload as any).last_words
    ) {
      const prevSpeech = (prev.payload.speech as string) || "";
      const curSpeech = (event.payload.speech as string) || "";
      merged[merged.length - 1] = {
        ...prev,
        payload: { ...prev.payload, speech: prevSpeech ? `${prevSpeech}\n\n${curSpeech}` : curSpeech },
      };
    } else {
      merged.push(event);
    }
  }
  return merged;
}

function isNightActionDetail(event: GameEvent, viewMode: ViewMode): boolean {
  if (viewMode === ViewMode.MODERATOR) return false;
  if (event.type !== EventType.NIGHT_ACTION) return false;
  const eventPhase = event.phase || (event.payload as any)?.phase || "";
  if (!eventPhase.startsWith("NIGHT_") || eventPhase === "NIGHT_START" || eventPhase === "NIGHT_RESOLVE") {
    return false;
  }
  return (event.payload as any)?.message !== "行动完毕";
}

// ── VoteResultInline ──────────────────────────────────────────────────

function VoteResultInline({ votes, players, language }: {
  votes: Record<string, string>; players: Player[]; language: Language;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, []);
  return (
    <div ref={ref}>
      <VoteResultPanel votes={votes} players={players} language={language} isBadgeVote={false} />
    </div>
  );
}

// ── DayEventBlock ────────────────────────────────────────────────────

export function DayEventBlock({
  day, events, language, viewMode, isHumanMode, humanSeat,
  completedIds, onChatComplete, hideDayHeaders, dayVotes, players,
  currentDay, speakerState,
}: DayEventBlockProps) {
  const rawEvents = events.filter(event =>
    event.type !== EventType.PRIVATE_INFO &&
    (viewMode === ViewMode.MODERATOR || event.visibility !== "private") &&
    !isRedundantPhaseAnnouncement(event) &&
    // 观众视角只看夜间完成摘要；全局视角保留夜间行动细节。
    !isNightActionDetail(event, viewMode) &&
    // 过滤投票放逐的 PLAYER_DIED 事件，统一在遗言后渲染一次确认
    !(event.type === EventType.PLAYER_DIED && (event.payload as any)?.reason === "vote")
  );

  const timelineEvents = mergeConsecutiveChats(rawEvents);
  const deaths = rawEvents.filter(e =>
    e.type === EventType.PLAYER_DIED || e.type === EventType.HUNTER_SHOT || e.type === EventType.WHITE_WOLF_KING_BOOM
  );

  if (timelineEvents.length === 0) return null;

  const visibleEvents = timelineEvents.filter(
    (event) => event.type !== EventType.CHAT_MESSAGE || completedIds.has(event.id),
  );

  // Vote result cutoff: show before LAST_WORDS / HUNTER_SHOOT / BADGE_TRANSFER
  let voteCutoff = visibleEvents.length;
  for (let i = 0; i < visibleEvents.length; i++) {
    const ph = visibleEvents[i].phase || "";
    if (ph === "DAY_LAST_WORDS" || ph === "HUNTER_SHOOT" || ph === "BADGE_TRANSFER") { voteCutoff = i; break; }
  }
  const voteResultReady = true;

  return (
    <div className="mb-5">
      {!hideDayHeaders && (
        <div className="mb-3 flex items-center gap-3 border-b border-border pb-2">
          <span className="font-display text-lg font-bold text-primary tracking-wide">
            {day === 0
              ? `🎭 ${t("dayHeaderSetup", language)}`
              : `🌅 ${t("dayHeaderLabel", language).replace("{n}", String(day))}`}
          </span>
          {deaths.length > 0 && (
            <span className="truncate text-xs text-danger">
              {deaths.map(d => d.payload.player_name || d.payload.target_name || "?").join(" · ")} {t("playerDied", language)}
            </span>
          )}
        </div>
      )}

      {/* Events — wolf deliberation inserted inline after NIGHT_WOLF_ACTION phase change */}
      <div className="space-y-0.5">
        {(() => {
          const nodes: React.ReactNode[] = [];
          const preCutoff = Math.min(voteCutoff, visibleEvents.length);

          for (let i = 0; i < preCutoff; i++) {
            const evt = visibleEvents[i];
            nodes.push(
              <TimelineEvent
                key={evt.id || i} event={evt} index={i}
                language={language} isHumanMode={isHumanMode} humanSeat={humanSeat}
                players={players}
                animateChat={false}
                onChatComplete={onChatComplete} isLatest={false}
              />
            );
          }

          // 插入发言思考阶段占位卡片
          if (
            speakerState?.state === "thinking" && 
            speakerState.speakerId && 
            players &&
            // 仅当前天的发言阶段显示
            day === currentDay &&
            visibleEvents.some(e => e.phase?.includes("SPEECH"))
          ) {
            const thinkingPlayer = players.find(p => p.id === speakerState.speakerId);
            if (thinkingPlayer) {
              nodes.push(
                <ChatBubble
                  key="thinking-placeholder"
                  speakerName={thinkingPlayer.name || "?"}
                  seat={thinkingPlayer.seat}
                  content={language === "zh" ? "正在组织语言..." : "Thinking..."}
                  isOwn={isHumanMode && thinkingPlayer.seat === humanSeat}
                  isSpeaking={false}
                  animate={false}
                  players={players}
                />
              );
            }
          }
          return nodes;
        })()}

        {/* Vote result inline */}
        {dayVotes && Object.keys(dayVotes).length > 0 && voteResultReady && (
          <VoteResultInline votes={dayVotes} players={players || []} language={language} />
        )}

        {visibleEvents.slice(voteCutoff).map((event, index) => (
          <TimelineEvent
            key={event.id || index} event={event} index={index + voteCutoff}
            language={language} isHumanMode={isHumanMode} humanSeat={humanSeat}
            players={players}
            animateChat={false}
            onChatComplete={onChatComplete}
            isLatest={false}
          />
        ))}

        {/* ── Elimination confirmation: once after last words ── */}
        {(() => {
          // Only for exile votes (not badge), and only after last words rendered
          if (!dayVotes || Object.keys(dayVotes).length === 0) return null;
          const hasLastWords = timelineEvents.some(e => e.phase === "DAY_LAST_WORDS");
          if (!hasLastWords) return null;
          // Find top vote getter
          const tally: Record<string, number> = {};
          for (const targetId of Object.values(dayVotes)) {
            tally[targetId] = (tally[targetId] || 0) + 1;
          }
          const topId = Object.entries(tally).sort((a, b) => b[1] - a[1])[0]?.[0];
          if (!topId) return null;
          const exiled = players?.find(p => p.id === topId);
          if (!exiled || exiled.alive) return null;
          const text = language === "zh"
            ? `${exiled.seat}号 ${exiled.name} 因投票放逐出局`
            : `#${exiled.seat} ${exiled.name} was exiled by vote`;
          return (
            <div className="flex justify-center py-2">
              <span className="text-xs text-danger/60 font-medium tracking-wide">
                ◆ {text}
              </span>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
