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
}

const systemIcons: Partial<Record<EventType, string>> = {
  [EventType.GAME_START]: "\u{1F3AE}",
  [EventType.GAME_END]: "\u{1F3C6}",
  [EventType.SYSTEM_MESSAGE]: "\u{1F4E2}",
};

function systemMessage(event: GameEvent, language: Language) {
  if (event.payload.phase) return tPhase(event.payload.phase, language);
  if (/^Night \d+ begins\.$/.test(event.payload.message || "")) return tPhase("NIGHT_START", language);
  if (/^Day \d+ begins\.$/.test(event.payload.message || "")) return tPhase("DAY_START", language);
  return event.payload.message ?? "";
}

export function EventTimeline({ dayBlocks, language, viewMode, isHumanMode, humanSeat }: EventTimelineProps) {
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
        />
      ))}
    </>
  );
}

function DayEventBlock({
  day,
  events,
  language,
  viewMode,
  isHumanMode,
  humanSeat,
}: {
  day: number;
  events: GameEvent[];
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
}) {
  const timelineEvents = events.filter((event) => event.type !== EventType.PRIVATE_INFO && (viewMode === ViewMode.MODERATOR || event.visibility !== "private"));
  const deaths = timelineEvents.filter((event) =>
    event.type === EventType.PLAYER_DIED || event.type === EventType.HUNTER_SHOT || event.type === EventType.WHITE_WOLF_KING_BOOM
  );

  if (timelineEvents.length === 0) return null;

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
        {timelineEvents.map((event, index) => (
          <TimelineEvent
            key={event.id || index}
            event={event}
            index={index}
            language={language}
            isHumanMode={isHumanMode}
            humanSeat={humanSeat}
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
}: {
  event: GameEvent;
  index: number;
  language: Language;
  isHumanMode: boolean;
  humanSeat: number;
}) {
  const isSystem = event.type === EventType.PHASE_CHANGED || event.type === EventType.GAME_START
    || event.type === EventType.GAME_END || event.type === EventType.SYSTEM_MESSAGE;

  if (isSystem) {
    const msg = systemMessage(event, language);
    const icon = systemIcons[event.type] || "";
    return <ChatBubble speakerName="" content={icon ? `${icon} ${msg}` : msg} isSystem />;
  }

  if (event.type === EventType.CHAT_MESSAGE) {
    return (
      <ChatBubble
        speakerName={event.payload.actor_name || "?"}
        content={event.payload.speech || ""}
        isOwn={isHumanMode && event.payload.actor_id?.startsWith(`P${humanSeat}-`)}
        phaseLabel={tPhase(event.phase, language)}
      />
    );
  }

  return <EventItem event={event} index={index} />;
}
