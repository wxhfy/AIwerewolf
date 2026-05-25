import { useMemo } from "react";
import { Alignment, GameEvent, GameState } from "@/types";

export function useGameDerivedState(gameState: GameState | null, humanSeat: number, isHumanMode: boolean) {
  const dayBlocks = useMemo(() => {
    if (!gameState?.events) return [];
    const blocks = new Map<number, GameEvent[]>();
    for (const event of gameState.events) {
      const day = event.day || 0;
      const events = blocks.get(day);
      if (events) {
        events.push(event);
      } else {
        blocks.set(day, [event]);
      }
    }
    return Array.from(blocks.entries()).sort(([a], [b]) => a - b);
  }, [gameState?.events]);

  const splitPoint = useMemo(() => Math.ceil((gameState?.players?.length || 7) / 2), [gameState?.players?.length]);
  const leftPlayers = useMemo(() => (gameState?.players || []).filter((player) => player.seat <= splitPoint), [gameState?.players, splitPoint]);
  const rightPlayers = useMemo(() => (gameState?.players || []).filter((player) => player.seat > splitPoint), [gameState?.players, splitPoint]);
  const humanPlayer = useMemo(() => (gameState?.players || []).find((player) => player.seat === humanSeat), [gameState?.players, humanSeat]);
  const wolfTeammates = useMemo(() => {
    if (!isHumanMode || humanPlayer?.alignment !== Alignment.WOLF) return undefined;
    return (gameState?.players || [])
      .filter((player) => player.alignment === Alignment.WOLF && player.seat !== humanSeat)
      .map((player) => player.name);
  }, [gameState?.players, humanPlayer, humanSeat, isHumanMode]);
  const badgeCandidateSet = useMemo(() => new Set(gameState?.badge?.candidates || []), [gameState?.badge?.candidates]);

  return {
    dayBlocks,
    splitPoint,
    leftPlayers,
    rightPlayers,
    aliveCount: gameState?.alive_count ?? (gameState?.players?.filter((player) => player.alive).length ?? 0),
    pendingInput: gameState?.pending_input,
    activeSpeakerId: gameState?.pending_input?.player_id || gameState?.current_speaker_id || null,
    sheriffId: gameState?.badge?.holder_id || null,
    badgeCandidateSet,
    wolfTeammates,
  };
}
