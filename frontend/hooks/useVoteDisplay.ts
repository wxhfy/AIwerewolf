"use client";

import { useMemo } from "react";
import { GameState } from "@/types";
import { isMergedChatSegment } from "@/lib/eventFilter";

export type VoteDisplayMode =
  | { type: "HIDDEN" }
  | { type: "LIVE_VOTING"; votes: Record<string, string>; phase: string }
  | { type: "BADGE_VOTING" }
  | { type: "RESULT"; votes: Record<string, string>; day: number };

export interface VoteDisplayData {
  /** Current display mode */
  mode: VoteDisplayMode;

  /** Events up to the first uncompleted CHAT_MESSAGE (for BadgePanel sync) */
  revealedEvents: import("@/types").GameEvent[];

  /** Badge vote tally: targetId → { count, voters } */
  badgeVoteTally: Map<string, { count: number; voters: string[] }>;

  /** Set of player IDs who have voted (from revealed events only) */
  votedSet: Set<string>;

  /** Set of badge candidate IDs who have spoken */
  badgeSpokenSet: Set<string>;
}

/**
 * Centralized vote display logic.
 *
 * Eliminates duplicate revealedEvents / voteTally computation previously
 * scattered across BadgePanel, page.tsx (VotePanel/VoteResultPanel), and
 * EventTimeline.
 */
export function useVoteDisplay(
  gameState: GameState | null,
  completedIds: Set<string>,
  completedTick: number,
  isTransitioning: boolean,
): VoteDisplayData {
  const phase = gameState?.phase || "";

  // ── Revealed events: up to first uncompleted CHAT_MESSAGE ──
  const revealedEvents = useMemo(() => {
    const events = gameState?.events;
    if (!events || events.length === 0) return [];

    let cutoff = events.length;
    let prevActor = "", prevPhase = "";
    for (let i = 0; i < events.length; i++) {
      const e = events[i];
      if (e.type === "CHAT_MESSAGE") {
        if (isMergedChatSegment(e, prevActor, prevPhase)) continue;
        prevActor = (e.payload as any)?.actor_id || "";
        prevPhase = e.phase || "";
        if (!completedIds.has(e.id)) {
          cutoff = i;
          break;
        }
      } else {
        prevActor = "";
        prevPhase = "";
      }
    }
    return events.slice(0, cutoff);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameState?.events, completedTick]);

  // ── Badge vote tally (from revealed events) ──
  const badgeVoteTally = useMemo(() => {
    const tally = new Map<string, { count: number; voters: string[] }>();
    for (const event of revealedEvents) {
      if (event.type !== "VOTE_CAST") continue;
      const p = event.payload as any;
      const voter = p.voter_id || "";
      const target = p.target_id || "";
      if (!voter || !target) continue;
      const entry = tally.get(target) || { count: 0, voters: [] };
      entry.count += 1;
      entry.voters.push(voter);
      tally.set(target, entry);
    }
    return tally;
  }, [revealedEvents]);

  // ── Voted set ──
  const votedSet = useMemo(() => {
    const set = new Set<string>();
    for (const event of revealedEvents) {
      if (event.type === "VOTE_CAST") {
        const voter = (event.payload as any)?.voter_id;
        if (voter) set.add(voter);
      }
    }
    return set;
  }, [revealedEvents]);

  // ── Badge spoken set ──
  const badgeCandidates = gameState?.badge?.candidates || [];
  const candidateSet = new Set(badgeCandidates);
  const badgeSpokenSet = useMemo(() => {
    const spoke = new Set<string>();
    for (const event of revealedEvents) {
      if (event.type === "CHAT_MESSAGE" && event.phase === "DAY_BADGE_SPEECH") {
        const actor = (event.payload as any)?.actor_id;
        if (actor && candidateSet.has(actor)) spoke.add(actor);
      }
    }
    return spoke;
  }, [revealedEvents, badgeCandidates]);

  // ── Mode determination ──
  const mode = useMemo((): VoteDisplayMode => {
    if (isTransitioning) return { type: "HIDDEN" };

    const isBadgeElection = phase === "DAY_BADGE_ELECTION";
    const isBadgeSpeech = phase === "DAY_BADGE_SPEECH" || phase === "DAY_BADGE_SIGNUP";
    const isVotePhase = (phase.includes("VOTE") || phase.includes("ELECTION")) && !phase.includes("BADGE");
    const isPkVote = phase === "DAY_PK_SPEECH" && gameState?.votes && Object.keys(gameState.votes).length > 0;

    // Badge phases
    if (isBadgeElection || isBadgeSpeech) {
      return { type: "BADGE_VOTING" };
    }

    // Live voting: exile vote or PK vote
    if (isVotePhase || isPkVote) {
      const votes = (gameState?.votes && Object.keys(gameState.votes).length > 0)
        ? gameState.votes
        : {};
      return { type: "LIVE_VOTING", votes, phase };
    }

    // Result: vote completed, history populated
    const voteHistory = gameState?.vote_history as Record<number, Record<string, string>> | undefined;
    if (voteHistory) {
      const days = Object.keys(voteHistory).map(Number).filter(n => !isNaN(n));
      if (days.length > 0) {
        const latestDay = Math.max(...days);
        const votes = voteHistory[latestDay];
        if (votes && Object.keys(votes).length > 0) {
          return { type: "RESULT", votes, day: latestDay };
        }
      }
    }

    return { type: "HIDDEN" };
  }, [phase, gameState?.votes, gameState?.vote_history, isTransitioning]);

  return { mode, revealedEvents, badgeVoteTally, votedSet, badgeSpokenSet };
}
