import { useMemo } from "react";
import { Alignment, EventType, GameEvent, GameState } from "@/types";

export function useGameDerivedState(gameState: GameState | null, humanSeat: number, isHumanMode: boolean, completedIds?: Set<string>, completedTick?: number) {
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

  // ── Revealed events only — syncs with EventTimeline revealIndex ──
  const revealedEvents = useMemo(() => {
    if (!gameState?.events) return [];
    const events = gameState.events;
    // Match EventTimeline's mergeConsecutiveChats: skip segments that
    // would be collapsed into the previous bubble.
    let cutoff = events.length;
    let prevActor = "", prevPhase = "";
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.type === EventType.CHAT_MESSAGE) {
        const actor = (e.payload as any)?.actor_id || "";
        const ph = e.phase || "";
        if (actor === prevActor && ph === prevPhase) continue; // merged segment
        prevActor = actor;
        prevPhase = ph;
        if (!completedIds?.has(e.id)) {
          cutoff = i;
          break;
        }
      } else {
        prevActor = "";
        prevPhase = "";
      }
    }
    return events.slice(0, cutoff);
  }, [gameState?.events, completedIds, completedTick]);

  // Tracks which players have spoken (from revealed events only)
  const spokenInPhase = useMemo(() => {
    const spoken = new Set<string>();
    if (!gameState?.phase) return spoken;
    for (const event of revealedEvents) {
      if (event.type === "CHAT_MESSAGE" && event.phase === gameState.phase) {
        const actorId = (event.payload as any)?.actor_id;
        if (actorId) spoken.add(actorId);
      }
    }
    return spoken;
  }, [revealedEvents, gameState?.phase]);

  // Tracks which players have voted (from revealed events only)
  const votedSet = useMemo(() => {
    const voted = new Set<string>();
    for (const event of revealedEvents) {
      if (event.type === EventType.VOTE_CAST) {
        const voterId = (event.payload as any)?.voter_id;
        if (voterId) voted.add(voterId);
      }
    }
    return voted;
  }, [revealedEvents]);

  // Vote tally per player (from revealed events only)
  const voteCount = useMemo(() => {
    const tally = new Map<string, number>();
    for (const event of revealedEvents) {
      if (event.type === EventType.VOTE_CAST) {
        const targetId = (event.payload as any)?.target_id;
        if (targetId) tally.set(targetId, (tally.get(targetId) || 0) + 1);
      }
    }
    return tally;
  }, [revealedEvents]);

  // Maps voterId → target player name (from revealed events only)
  const voteTarget = useMemo(() => {
    const map = new Map<string, string>();
    if (!gameState?.players) return map;
    for (const event of revealedEvents) {
      if (event.type === EventType.VOTE_CAST) {
        const p = event.payload as any;
        const voterId = p.voter_id;
        const targetId = p.target_id;
        if (!voterId || !targetId) continue;
        const target = gameState.players.find(pl => pl.id === targetId);
        if (target) map.set(voterId, target.name);
      }
    }
    return map;
  }, [revealedEvents, gameState?.players]);

  // Dead player state machine: last_words | hunter_shoot | spectating | null
  const deadPlayerState = useMemo(() => {
    if (!gameState?.players || !isHumanMode) return null;
    const me = gameState.players.find((p) => p.seat === humanSeat);
    if (!me || me.alive) return null;

    const pending = gameState.pending_input;
    const isLastWords = gameState.phase === "DAY_LAST_WORDS" && pending?.player_id === me.id;
    const isHunterShoot = gameState.phase === "HUNTER_SHOOT" && pending?.player_id === me.id;

    if (isHunterShoot) return "hunter_shoot" as const;
    if (isLastWords) return "last_words" as const;
    return "spectating" as const;
  }, [gameState?.players, gameState?.phase, gameState?.pending_input, humanSeat, isHumanMode]);

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
    spokenInPhase,
    votedSet,
    voteCount,
    voteTarget,
    deadPlayerState,
  };
}
