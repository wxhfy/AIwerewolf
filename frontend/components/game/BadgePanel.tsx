"use client";

import React from "react";
import { GameState, Language } from "@/types";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface BadgePanelProps {
  gameState: GameState;
  language: Language;
  activeSpeakerId: string | null;
  displayPhase?: string;
  /** Typewriter-completed CHAT_MESSAGE IDs — syncs data visibility with EventTimeline */
  completedIds: Set<string>;
}

export function BadgePanel({ gameState, language, activeSpeakerId, displayPhase, completedIds }: BadgePanelProps) {
  const phase = displayPhase || gameState.phase;
  const isBadgeSpeech = phase === "DAY_BADGE_SPEECH" || phase === "DAY_BADGE_SIGNUP";
  const isBadgeElection = phase === "DAY_BADGE_ELECTION";
  const isDayVote = phase === "DAY_VOTE";
  const isPkVote = phase === "DAY_PK_SPEECH" || (phase === "DAY_VOTE" && (gameState.pk_targets?.length ?? 0) > 0);

  if (!isBadgeSpeech && !isBadgeElection && !isDayVote) return null;

  const badge = gameState.badge;
  const candidates = badge?.candidates || [];
  const players = gameState.players || [];
  const pkTargets = new Set(gameState.pk_targets || []);

  // ── Compute reveal cutoff (match EventTimeline's mergeConsecutiveChats) ─
  // EventTimeline merges consecutive same-player same-phase CHAT_MESSAGE
  // into one bubble (first segment's id enters completedIds).  We must
  // skip subsequent segments here too or they block the cutoff early.
  let revealCutoff = (gameState.events || []).length;
  let prevActor = "", prevPhase = "";
  for (let i = 0; i < (gameState.events || []).length; i++) {
    const e = gameState.events[i];
    if (e.type === "CHAT_MESSAGE") {
      const actor = (e.payload as any)?.actor_id || "";
      const ph = e.phase || "";
      // Skip segments that mergeConsecutiveChats would collapse — they
      // share the completed status of the first segment.
      if (actor === prevActor && ph === prevPhase) continue;
      prevActor = actor;
      prevPhase = ph;
      if (!completedIds.has(e.id)) {
        revealCutoff = i;
        break;
      }
    } else {
      prevActor = "";
      prevPhase = "";
    }
  }
  const revealedEvents = (gameState.events || []).slice(0, revealCutoff);

  // ── Speech progress: only count badge CANDIDATES who spoke ──────
  const candidateSet = new Set(candidates);
  const spokenSet = new Set<string>();
  for (const event of revealedEvents) {
    if (event.type === "CHAT_MESSAGE" && event.phase === "DAY_BADGE_SPEECH") {
      const actorId = (event.payload as any)?.actor_id;
      if (actorId && candidateSet.has(actorId)) spokenSet.add(actorId);
    }
  }

  // ── Vote tally (from revealed events only, NOT raw gameState.votes) ─
  const voteTally = new Map<string, { count: number; voters: string[] }>();
  const votedSet = new Set<string>();
  for (const event of revealedEvents) {
    if (event.type === "VOTE_CAST") {
      const p = event.payload as any;
      const voter = p.voter_id || "";
      const target = p.target_id || "";
      if (!voter || !target) continue;
      votedSet.add(voter);
      const entry = voteTally.get(target) || { count: 0, voters: [] };
      entry.count += 1;
      entry.voters.push(voter);
      voteTally.set(target, entry);
    }
  }

  const aliveCount = players.filter(p => p.alive).length;
  const totalVoters = aliveCount;
  const voteProgress = totalVoters > 0 ? votedSet.size / totalVoters : 0;
  const allVoted = votedSet.size >= totalVoters;

  // Leading vote-getter
  let leadingId = "";
  let leadingCount = 0;
  for (const [tid, { count }] of voteTally) {
    if (count > leadingCount) { leadingCount = count; leadingId = tid; }
  }

  // ── Title ───────────────────────────────────────────────────────
  const titleText = isBadgeSpeech
    ? (language === "zh" ? "警徽竞选发言" : "Badge Speech")
    : isBadgeElection
    ? (language === "zh" ? "警徽投票" : "Badge Vote")
    : isPkVote
    ? (language === "zh" ? "PK 投票" : "PK Vote")
    : (language === "zh" ? "投票放逐" : "Vote");

  const subtitle = isBadgeSpeech
    ? (candidates.length > 0 ? `${spokenSet.size}/${candidates.length} ${language === "zh" ? "已发言" : "spoken"}` : "")
    : (totalVoters > 0 ? `${votedSet.size}/${totalVoters} ${language === "zh" ? "已投票" : "voted"}` : "");

  return (
    <div className="border-b border-border bg-cardBackground/80 px-5 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-primary">{titleText}</span>
        <span className="text-xs text-text-sub">{subtitle}</span>
      </div>

      {/* Vote progress bar */}
      {!isBadgeSpeech && (
        <div className="mb-3 h-1.5 rounded-full overflow-hidden bg-border">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              allVoted ? "bg-success" : "bg-primary",
            )}
            style={{ width: `${voteProgress * 100}%` }}
          />
        </div>
      )}

      {/* Candidate / target list */}
      <div className="flex flex-wrap gap-2">
        {isBadgeSpeech && candidates.map(cid => {
          const p = players.find(pl => pl.id === cid);
          const spoken = spokenSet.has(cid);
          const isSpeaking = activeSpeakerId === cid;
          return (
            <span key={cid} className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium border transition-all",
              isSpeaking && "border-success bg-success/10 text-success ring-1 ring-success/30",
              spoken && !isSpeaking && "border-primary/30 bg-primary/5 text-primary",
              !spoken && !isSpeaking && "border-border text-text-sub",
            )}>
              {p ? `${p.seat}号 ${p.name}` : cid}
              {spoken && <span className="text-[10px]">✓</span>}
              {isSpeaking && <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />}
            </span>
          );
        })}

        {(isBadgeElection || isDayVote) && voteTally.size > 0 && (
          Array.from(voteTally.entries())
            .sort(([, a], [, b]) => b.count - a.count)
            .map(([tid, { count }], idx) => {
              const p = players.find(pl => pl.id === tid);
              const isPk = pkTargets.has(tid);
              const isLeading = tid === leadingId && leadingCount > 0 && idx === 0;
              return (
                <span key={tid} className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium border transition-all",
                  isLeading && "ring-2 ring-accent/40",
                  isPk ? "border-warning/40 bg-warning/5 text-warning" : "border-accent/30 bg-accent/5 text-accent",
                )}>
                  {p ? `${p.seat}号 ${p.name}` : tid}
                  <span className={cn("font-bold", isLeading && "text-accent")}>{count}{language === "zh" ? "票" : ""}</span>
                  {isLeading && voteTally.size > 1 && <span className="text-[10px] text-accent">领先</span>}
                </span>
              );
            })
        )}
      </div>

      {/* Unvoted / next-step hint */}
      {isBadgeSpeech && candidates.length > 0 && spokenSet.size < candidates.length && (
        <div className="mt-2 text-xs text-text-sub/60">
          {language === "zh" ? "全部发言完成后进入投票环节" : "Voting begins after all speeches"}
        </div>
      )}
      {(isBadgeElection || isDayVote) && !allVoted && (
        <div className="mt-2 text-xs text-text-sub/60">
          {language === "zh" ? "等待：" : "Waiting: "}
          {players.filter(p => p.alive && !votedSet.has(p.id)).map(p => `${p.seat}号 ${p.name}`).join(" · ")}
        </div>
      )}
      {(isBadgeElection || isDayVote) && allVoted && leadingCount > 0 && (
        <div className="mt-2 text-xs text-accent font-medium">
          {isBadgeElection
            ? (language === "zh" ? "投票完成，即将公布警长结果" : "Vote complete — sheriff result incoming")
            : (language === "zh" ? "投票完成，即将公布放逐结果" : "Vote complete — exile result incoming")}
        </div>
      )}
    </div>
  );
}
