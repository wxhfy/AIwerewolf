import { GameEvent } from "@/types";

export type ViewMode = "player" | "public" | "host";

/**
 * Filter events by visibility rules:
 * - "public" events: everyone sees
 * - "private" events: only players in visible_to list OR host mode
 * - PRIVATE_INFO type: always hidden from public, visible to the target player or host
 */
export function filterEvents(
  events: GameEvent[],
  viewMode: ViewMode,
  currentPlayerId?: string,
): GameEvent[] {
  if (viewMode === "host") return events; // Host sees everything

  return events.filter((event) => {
    // Public events: always visible
    if (event.visibility === "public") return true;

    // PRIVATE_INFO: only visible to the target player or host
    if (event.type === "PRIVATE_INFO") {
      if (viewMode === "player" && currentPlayerId) {
        return (event.visible_to || []).includes(currentPlayerId);
      }
      return false;
    }

    // Private events: only visible to players in visible_to list
    if (event.visibility === "private") {
      if (viewMode === "player" && currentPlayerId) {
        return (event.visible_to || []).includes(currentPlayerId);
      }
      return false;
    }

    // Unknown visibility: hide in non-host mode
    return false;
  });
}
