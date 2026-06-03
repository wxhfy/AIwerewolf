"use client";

import { useMemo } from "react";
import { GameState, Player, PendingInput } from "@/types";

export interface HumanDisplayState {
  phase: string;
  phaseLabel: string;
  cycle: string;
  isNight: boolean;
  isOver: boolean;

  currentActor: { seat: number; name: string; id: string } | null;
  isMyTurn: boolean;
  canAct: boolean;

  myRole: string;
  myAlignment: string;
  myName: string;
  mySeat: number;
  wolfTeammates: string[];

  voteResultMsg: string | null;
  deathNames: string[];

  aliveCount: number;
  totalCount: number;
  sheriffSeat: number | null;
}

// ── Phase → Chinese label ────────────────────────────────────────
const PHASE_LABEL: Record<string, string> = {
  SETUP: "准备阶段", NIGHT_START: "夜幕降临", NIGHT_GUARD_ACTION: "守卫行动",
  NIGHT_WOLF_ACTION: "狼人行动", NIGHT_WITCH_ACTION: "女巫行动", NIGHT_SEER_ACTION: "预言家行动",
  NIGHT_RESOLVE: "夜晚结算", DAY_START: "天亮了", DAY_BADGE_SIGNUP: "警徽报名",
  DAY_BADGE_SPEECH: "警徽竞选发言", DAY_BADGE_ELECTION: "警徽投票",
  DAY_PK_SPEECH: "PK 发言", DAY_SPEECH: "自由发言", DAY_VOTE: "投票放逐",
  DAY_LAST_WORDS: "遗言", DAY_RESOLVE: "白天结算", HUNTER_SHOOT: "猎人开枪",
  BADGE_TRANSFER: "警徽移交", GAME_END: "游戏结束",
};

const ROLE_PHASE: Record<string, string> = {
  Guard: "NIGHT_GUARD_ACTION", Werewolf: "NIGHT_WOLF_ACTION",
  WhiteWolfKing: "NIGHT_WOLF_ACTION", Seer: "NIGHT_SEER_ACTION",
  Witch: "NIGHT_WITCH_ACTION", Hunter: "HUNTER_SHOOT",
};

/**
 * Single source of truth for human mode page. All components (StatusBar,
 * HumanStageArea, ActionPanel, PlayerCards, EventTimeline) read from this
 * object — no more scattered `useMemo`s or disjoint derived state.
 */
export function useHumanDisplayState(
  gameState: GameState | null,
  humanPlayer: Player | undefined,
  viewMode: string,
): HumanDisplayState {
  return useMemo(() => {
    if (!gameState) {
      return {
        phase: "", phaseLabel: "", cycle: "", isNight: false, isOver: false,
        currentActor: null, isMyTurn: false, canAct: false,
        myRole: "", myAlignment: "", myName: "", mySeat: 0, wolfTeammates: [],
        voteResultMsg: null, deathNames: [], aliveCount: 0, totalCount: 0, sheriffSeat: null,
      };
    }

    const phase = gameState.phase;
    const day = gameState.day || 0;
    const isNight = phase.startsWith("NIGHT") || phase === "SETUP";
    const isOver = phase === "GAME_END" || !!gameState.winner;
    const cycle = isOver ? "游戏结束" : day === 0 ? "准备阶段" : isNight ? `第 ${day} 夜` : `第 ${day} 天`;

    const players = gameState.players || [];
    const aliveCount = players.filter((p) => p.alive).length;
    const totalCount = players.length;

    // ── Current actor ─────────────────────────────────────────────
    const pending = gameState.pending_input as PendingInput | undefined;
    const actorId = pending?.player_id || gameState.current_speaker_id || "";
    const actorP = players.find((p) => p.id === actorId && p.alive);
    const currentActor = actorP ? { seat: actorP.seat, name: actorP.name, id: actorP.id } : null;

    // ── My turn / canAct ──────────────────────────────────────────
    const isMyTurn = !!(pending && humanPlayer && pending.player_id === humanPlayer.id);
    const myRole = (humanPlayer?.role as string) || "";
    const myRolePhase = ROLE_PHASE[myRole] || "";
    const canAct = isMyTurn && (
      phase.includes("SPEECH") || phase.includes("VOTE") || phase.includes("BADGE") ||
      phase.includes("LAST_WORDS") || phase === myRolePhase || phase === "HUNTER_SHOOT"
    );

    // ── Identity ──────────────────────────────────────────────────
    const myAlignment = humanPlayer?.alignment || "";
    const myName = humanPlayer?.name || "";
    const mySeat = humanPlayer?.seat || 0;
    const wolfTeammates: string[] = [];
    if (myAlignment === "wolf" && humanPlayer) {
      for (const p of players) {
        if (p.alignment === "wolf" && p.id !== humanPlayer.id) wolfTeammates.push(p.name);
      }
    }

    // ── Vote result ───────────────────────────────────────────────
    let voteResultMsg: string | null = null;
    const events = gameState.events || [];
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i] as any;
      if (e.type === "SYSTEM_MESSAGE" && (e.payload?.message || "").includes("was voted out")) {
        voteResultMsg = e.payload.message;
        break;
      }
    }

    // ── Death results ─────────────────────────────────────────────
    const deathNames: string[] = [];
    for (const e of events) {
      if (e.type === "PLAYER_DIED" || e.type === "HUNTER_SHOT") {
        const name = (e.payload as any)?.player_name || (e.payload as any)?.target_name || "";
        if (name) deathNames.push(name);
      }
    }

    // ── Sheriff ───────────────────────────────────────────────────
    const sheriffSeat = gameState.badge?.holder_id
      ? players.find((p) => p.id === gameState.badge?.holder_id)?.seat || null
      : null;

    return {
      phase, phaseLabel: PHASE_LABEL[phase] || phase, cycle, isNight, isOver,
      currentActor, isMyTurn, canAct,
      myRole, myAlignment, myName, mySeat, wolfTeammates,
      voteResultMsg, deathNames, aliveCount, totalCount, sheriffSeat,
    };
  }, [gameState, humanPlayer, viewMode]);
}
