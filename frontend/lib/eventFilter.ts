import { EventType, GameEvent } from "@/types";

export type ViewMode = "player" | "public" | "host";

type UiChatPayload = GameEvent["payload"] & {
  last_words?: boolean;
  merged_event_ids?: string[];
  segment_total?: number;
};

function getUiChatPayload(event: GameEvent): UiChatPayload {
  return event.payload as UiChatPayload;
}

/**
 * Filter events by visibility rules.
 */
export function filterEvents(
  events: GameEvent[],
  viewMode: ViewMode,
  currentPlayerId?: string,
): GameEvent[] {
  if (viewMode === "host") return events;

  return events.filter((event) => {
    if (event.visibility === "public") return true;

    if (event.type === "PRIVATE_INFO") {
      if (viewMode === "player" && currentPlayerId) {
        return (event.visible_to || []).includes(currentPlayerId);
      }
      return false;
    }

    if (event.visibility === "private") {
      if (viewMode === "player" && currentPlayerId) {
        return (event.visible_to || []).includes(currentPlayerId);
      }
      return false;
    }

    return false;
  });
}

/**
 * Detects whether a CHAT_MESSAGE event should be skipped because
 * mergeConsecutiveChats would collapse it into the previous bubble.
 *
 * Condition: same actor_id, same phase, consecutive in the event array,
 * and neither is a "last_words" message.
 *
 * Used by: EventTimeline (mergeConsecutiveChats), BadgePanel (revealCutoff),
 *          useGamePageController (displayPhase).
 */
export function isMergedChatSegment(
  event: GameEvent,
  prevActor: string,
  prevPhase: string,
): boolean {
  if (event.type !== EventType.CHAT_MESSAGE) return false;
  // Don't skip multi-segment speeches — they are separate intentional bubbles
  if ((getUiChatPayload(event).segment_total || 0) > 1) return false;
  const actor = getUiChatPayload(event).actor_id || "";
  const phase = event.phase || "";
  if (!actor || !phase) return false;
  return actor === prevActor && phase === prevPhase;
}

/**
 * Whether this chat event should block timeline reveal / bottom typewriter.
 * Multi-segment speeches intentionally block one segment at a time; older
 * same-actor same-phase events that are not explicit segments may still be
 * collapsed into the previous bubble.
 */
export function isRevealBlockingChat(
  event: GameEvent,
  prevActor: string,
  prevPhase: string,
): boolean {
  return event.type === EventType.CHAT_MESSAGE && !isMergedChatSegment(event, prevActor, prevPhase);
}

export function canMergeChatEvents(prev: GameEvent | undefined, event: GameEvent): boolean {
  if (!prev) return false;
  if (event.type !== EventType.CHAT_MESSAGE || prev.type !== EventType.CHAT_MESSAGE) return false;
  const eventPayload = getUiChatPayload(event);
  const prevPayload = getUiChatPayload(prev);
  const isExplicitMultiSegment = (eventPayload.segment_total || 0) > 1 || (prevPayload.segment_total || 0) > 1;
  if (isExplicitMultiSegment) return false;
  return Boolean(
    event.payload.actor_id &&
    event.payload.actor_id === prev.payload.actor_id &&
    event.phase === prev.phase &&
    !eventPayload?.last_words &&
    !prevPayload?.last_words,
  );
}

/**
 * Merge legacy consecutive same-actor same-phase chat events into the exact
 * bubble displayed in the timeline. BottomDialogueDock also uses this helper,
 * so the live typewriter text and the finalized log bubble stay identical.
 */
export function mergeConsecutiveChats(events: GameEvent[]): GameEvent[] {
  const merged: GameEvent[] = [];
  for (const event of events) {
    const prev = merged[merged.length - 1];
    if (canMergeChatEvents(prev, event)) {
      const prevSpeech = (prev.payload.speech as string) || "";
      const curSpeech = (event.payload.speech as string) || "";
      const prevIds = getUiChatPayload(prev).merged_event_ids || [prev.id];
      const payload: UiChatPayload = {
        ...prev.payload,
        speech: prevSpeech ? `${prevSpeech}\n\n${curSpeech}` : curSpeech,
        merged_event_ids: [...prevIds, event.id],
      };
      merged[merged.length - 1] = {
        ...prev,
        payload,
      };
    } else {
      merged.push(event);
    }
  }
  return merged;
}

export function getChatCompletionIds(event: GameEvent): string[] {
  const mergedIds = getUiChatPayload(event).merged_event_ids;
  return Array.isArray(mergedIds) && mergedIds.every((id) => typeof id === "string")
    ? mergedIds
    : [event.id];
}

export function isChatCompleted(event: GameEvent, completedIds: Set<string>): boolean {
  return getChatCompletionIds(event).every((id) => completedIds.has(id));
}

export function getRevealCutoff(events: GameEvent[], completedIds: Set<string>): number {
  const merged = mergeConsecutiveChats(events);
  for (let i = 0; i < merged.length; i++) {
    const event = merged[i];
    if (event.type === EventType.CHAT_MESSAGE && !isChatCompleted(event, completedIds)) {
      const rawIndex = events.findIndex((raw) => raw.id === event.id);
      return rawIndex >= 0 ? rawIndex : events.length;
    }
  }
  return events.length;
}

export function getRevealedEvents(events: GameEvent[], completedIds: Set<string>): GameEvent[] {
  return events.slice(0, getRevealCutoff(events, completedIds));
}

/**
 * Iterates CHAT_MESSAGE events, skipping merged segments.
 * After a non-chat event, prevActor/prevPhase are reset.
 *
 * Returns a tuple [shouldContinue, actor, phase] for each CHAT_MESSAGE.
 * Caller provides the logic to execute on non-merged segments.
 */
export function forEachVisibleChat(
  events: GameEvent[],
  onSegment: (event: GameEvent, index: number) => boolean | void,
): void {
  let prevActor = "";
  let prevPhase = "";
  for (let i = 0; i < events.length; i++) {
    const e = events[i];
    if (e.type === EventType.CHAT_MESSAGE) {
      if (!isRevealBlockingChat(e, prevActor, prevPhase)) continue;
      prevActor = getUiChatPayload(e).actor_id || "";
      prevPhase = e.phase || "";
      const shouldStop = onSegment(e, i);
      if (shouldStop) return;
    } else {
      prevActor = "";
      prevPhase = "";
    }
  }
}

/**
 * 统一发言内容规范化。
 *
 * 空发言（null / undefined / 空字符串 / 纯空白 / 仅换行）统一兜底为 fallbackText。
 * 所有发言入口（TimelineEvent、ChatBubble）都应通过此函数处理 content。
 */
export function normalizeSpeechContent(raw: unknown, fallbackText: string): string {
  if (raw == null) return fallbackText || "发言完毕，过。";
  const s = String(raw)
    .replace(/[ \t]*\\+[ \t]*(\r?\n)/g, "$1")
    .trim();
  return s.length > 0 ? s : fallbackText || "发言完毕，过。";
}
