import { Phase } from "@/types";

export type PhaseGroup = "day" | "night" | "end" | "other";

const nightPhases = new Set<string>([
  Phase.NIGHT_START,
  Phase.NIGHT_GUARD_ACTION,
  Phase.NIGHT_WOLF_ACTION,
  Phase.NIGHT_WITCH_ACTION,
  Phase.NIGHT_SEER_ACTION,
  Phase.NIGHT_RESOLVE,
]);

const dayPhases = new Set<string>([
  Phase.DAY_START,
  Phase.DAY_BADGE_SIGNUP,
  Phase.DAY_BADGE_SPEECH,
  Phase.DAY_BADGE_ELECTION,
  Phase.DAY_PK_SPEECH,
  Phase.DAY_LAST_WORDS,
  Phase.DAY_SPEECH,
  Phase.DAY_VOTE,
  Phase.DAY_RESOLVE,
  Phase.BADGE_TRANSFER,
  Phase.HUNTER_SHOOT,
  Phase.WHITE_WOLF_KING_BOOM,
]);

export function getPhaseGroup(phase?: string): PhaseGroup {
  if (!phase) return "other";
  if (phase === Phase.GAME_END) return "end";
  if (nightPhases.has(phase)) return "night";
  if (dayPhases.has(phase)) return "day";
  return "other";
}
