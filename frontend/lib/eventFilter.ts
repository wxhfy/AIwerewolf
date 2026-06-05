import { EventType, GameEvent } from "@/types";

export type ViewMode = "player" | "public" | "host";

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
  if ((event.payload as any)?.segment_total > 1) return false;
  const actor = (event.payload as any)?.actor_id || "";
  const phase = event.phase || "";
  if (!actor || !phase) return false;
  return actor === prevActor && phase === prevPhase;
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
      if (isMergedChatSegment(e, prevActor, prevPhase)) continue;
      prevActor = (e.payload as any)?.actor_id || "";
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
  const s = String(raw).trim();
  return s.length > 0 ? s : fallbackText || "发言完毕，过。";
}
