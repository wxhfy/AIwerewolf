import { useMemo } from "react";
import { Alignment, EventType, GameEvent, GameState, Phase } from "@/types";
import { isRevealBlockingChat } from "@/lib/eventFilter";

/**
 * 夜间阶段 → 对应角色列表。
 * NIGHT_WOLF_ACTION 包含 Werewolf 和 WhiteWolfKing（白狼王是狼变体）。
 */
const NIGHT_PHASE_ROLES: Partial<Record<string, string[]>> = {
  [Phase.NIGHT_GUARD_ACTION]: ["Guard"],
  [Phase.NIGHT_WOLF_ACTION]: ["Werewolf", "WhiteWolfKing"],
  [Phase.NIGHT_WITCH_ACTION]: ["Witch"],
  [Phase.NIGHT_SEER_ACTION]: ["Seer"],
};

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
        if (!isRevealBlockingChat(e, prevActor, prevPhase)) continue;
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

  // ── Night role highlighting ──────────────────────────────────────────
  // When in a night action phase, derive which roles are active so
  // PlayerCards can highlight the corresponding players.
  const nightRoleInfo = useMemo(() => {
    const phase = gameState?.phase || "";
    const roles = NIGHT_PHASE_ROLES[phase];
    if (!roles || roles.length === 0) return null;

    // Specific actor from pending_input (e.g. the guard player currently deciding)
    const pendingActorId = gameState?.pending_input?.player_id || null;

    // Collect alive player IDs whose role matches the current night phase
    const roleMatchedIds: string[] = [];
    for (const p of gameState?.players || []) {
      if (p.alive && p.role && roles.includes(p.role)) {
        roleMatchedIds.push(p.id);
      }
    }

    return { roles, pendingActorId, roleMatchedIds };
  }, [gameState?.phase, gameState?.players, gameState?.pending_input?.player_id]);

  // 统一发言阶段状态：thinking → speaking → finished
  // 覆盖：SPEECH 阶段 + VOTE 阶段（警长归票）+ PK 阶段
  const speakerState = useMemo(() => {
    const phase = gameState?.phase || "";
    const isSpeechLike = phase.includes("SPEECH") || phase.includes("VOTE") || phase.includes("PK") || phase.includes("CLOSING");
    if (!isSpeechLike) return { state: "finished" as const, speakerId: null };

    // ── 1. 发言中：找 events 里当前阶段最新一条未完成的 CHAT_MESSAGE ──
    // 不依赖 current_speaker_id，因为后端可能在 CHAT_MESSAGE 到达的同一帧
    // 就把 current_speaker_id 切到了下一个人，导致说话者状态丢失
    const lastUncompleted = [...(gameState?.events || [])].reverse().find(e =>
      e.type === "CHAT_MESSAGE" && e.phase === phase && !completedIds?.has(e.id)
    );
    if (lastUncompleted) {
      const actorId = (lastUncompleted.payload as any)?.actor_id as string || "";
      return { state: "speaking" as const, speakerId: actorId };
    }

    // ── 2. 思考中：current_speaker_id 指向的玩家还没有 CHAT_MESSAGE ──
    const pendingId = gameState?.pending_input?.player_id;
    const speakerId = pendingId || gameState?.current_speaker_id || null;
    if (speakerId) {
      const hasChat = gameState?.events?.some(e =>
        e.type === "CHAT_MESSAGE" && e.payload.actor_id === speakerId && e.phase === phase
      );
      if (!hasChat) return { state: "thinking" as const, speakerId };
    }

    // ── 3. 已完成或无当前发言者 ──
    return { state: "finished" as const, speakerId: null };
  }, [gameState?.phase, gameState?.pending_input?.player_id, gameState?.events, completedIds, completedTick]);

  return {
    dayBlocks,
    splitPoint,
    leftPlayers,
    rightPlayers,
    aliveCount: gameState?.alive_count ?? (gameState?.players?.filter((player) => player.alive).length ?? 0),
    pendingInput: gameState?.pending_input,
    // activeSpeakerId: pending_input first, current_speaker_id during SPEECH phases,
    // and during voting phases, the next unvoted player from VOTE_CAST events
    activeSpeakerId: (() => {
      const phase = gameState?.phase || "";
      const pendingId = gameState?.pending_input?.player_id;
      if (pendingId) return pendingId;
      // Speech phases: fall back to current_speaker_id
      if (phase.includes("SPEECH")) return gameState?.current_speaker_id || null;
      // Vote/election phases: find next unvoted player from VOTE_CAST events
      if (phase.includes("VOTE") || phase.includes("ELECTION")) {
        const voted = new Set<string>();
        for (const e of gameState?.events || []) {
          if (e.type === "VOTE_CAST") {
            const vid = (e.payload as any)?.voter_id;
            if (vid) voted.add(vid);
          }
        }
        // 警徽选举阶段：候选人没有投票权，排除候选人
        const isBadgeElection = phase === "DAY_BADGE_ELECTION";
        const next = (gameState?.players || []).find(p => 
          p.alive && 
          !voted.has(p.id) &&
          // 警徽选举时排除候选人
          !(isBadgeElection && badgeCandidateSet.has(p.id))
        );
        return next?.id || null;
      }
      return null;
    })(),
    speakerState,
    sheriffId: gameState?.badge?.holder_id || null,
    badgeCandidateSet,
    wolfTeammates,
    spokenInPhase,
    deadPlayerState,
    nightRoleInfo,
  };
}
