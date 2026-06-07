"use client";

import React from "react";
import { GameEvent, Language, ViewMode, Player } from "@/types";
import { DayEventBlock } from "@/components/game/_speech/DayEventBlock";

// ── Types ────────────────────────────────────────────────────────────

interface EventTimelineProps {
  dayBlocks: Array<[number, GameEvent[]]>;
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
  completedIds: Set<string>;
  onChatComplete: (eventId: string) => void;
  hideDayHeaders?: boolean;
  dayVotes?: Record<number, Record<string, string>>;
  players?: Player[];
  isTransitioning?: boolean;
  currentDay?: number;
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
}

/**
 * EventTimeline — 纯编排层。
 *
 * 职责：按 day 分组事件，传递给 DayEventBlock 渲染。
 * 所有展示逻辑（合并发言、狼队商议、投票结果、打字机队列）在 DayEventBlock 中。
 */
export function EventTimeline({
  dayBlocks, language, viewMode, isHumanMode, humanSeat,
  completedIds, onChatComplete, hideDayHeaders, dayVotes, players,
  isTransitioning, currentDay, speakerState,
}: EventTimelineProps) {
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
          hideDayHeaders={hideDayHeaders}
          dayVotes={dayVotes?.[day]}
          players={players}
          isTransitioning={isTransitioning}
          currentDay={currentDay}
          speakerState={speakerState}
        />
      ))}
    </>
  );
}
