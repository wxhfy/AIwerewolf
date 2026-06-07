"use client";

import React from "react";
import { GameState, Language } from "@/types";
import { cn } from "@/lib/utils";
import { isRevealBlockingChat } from "@/lib/eventFilter";

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
  // VotePanel 负责所有投票展示（放逐投票 + PK 投票），BadgePanel 只负责
  // 警徽竞选发言和警徽投票（候选人视角的票数统计）

  if (!isBadgeSpeech && !isBadgeElection) return null;

  const badge = gameState.badge;
  // 后端在选举开始后可能清空 badge.candidates，从投票数据反推候选人
  const candidates = badge?.candidates?.length
    ? badge.candidates
    : [...new Set(Object.values(badge?.votes || {}))].filter(Boolean);
  const players = gameState.players || [];
  const pkTargets = new Set(gameState.pk_targets || []);

  // ── Compute reveal cutoff (match EventTimeline's mergeConsecutiveChats) ─
  let revealCutoff = (gameState.events || []).length;
  let prevActor = "", prevPhase = "";
  for (let i = 0; i < (gameState.events || []).length; i++) {
    const e = gameState.events[i];
    if (e.type === "CHAT_MESSAGE") {
      if (!isRevealBlockingChat(e, prevActor, prevPhase)) continue;
      prevActor = (e.payload as any)?.actor_id || "";
      prevPhase = e.phase || "";
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
  // 警徽竞选时，候选人只被投、不参与投票。分母排除候选人。
  const totalVoters = isBadgeElection
    ? players.filter(p => p.alive && !candidateSet.has(p.id)).length
    : aliveCount;
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
    : (language === "zh" ? "警徽投票" : "Badge Vote");

  const subtitle = isBadgeSpeech
    ? (candidates.length > 0 ? `${spokenSet.size}/${candidates.length} ${language === "zh" ? "已发言" : "spoken"}` : "")
    : (totalVoters > 0 ? `${votedSet.size}/${totalVoters} ${language === "zh" ? "已投票" : "voted"}` : "");

  return (
    <div className={cn(
      isBadgeElection 
        ? "mx-4 mt-3 rounded-xl border border-border/50 bg-cardBackground/60 backdrop-blur-sm overflow-hidden"
        : "border-b border-border bg-gradient-to-b from-cardBackground/95 to-cardBackground/90 backdrop-blur-sm px-5 py-4 shadow-sm"
    )}>
      <div className={cn(
        "flex items-center gap-2",
        isBadgeElection ? "justify-between px-4 py-2.5 border-b border-border/30" : "mb-2.5"
      )}>
        <div className="flex items-center gap-2">
          {isBadgeElection && <span className="text-base">🗳</span>}
          <span className={cn("text-sm font-semibold", isBadgeElection ? "text-textPrimary" : "text-primary")}>{titleText}</span>
        </div>
        {isBadgeElection && (
          <span className="text-xs text-text-sub tabular-nums">
            {language === "zh" ? `已投 ${votedSet.size}/${totalVoters}` : `Voted ${votedSet.size}/${totalVoters}`}
          </span>
        )}
        {!isBadgeElection && <span className="text-xs text-text-sub/80">{subtitle}</span>}
      </div>

      {/* Vote progress bar */}
      {!isBadgeSpeech && (
        <div className="h-1 bg-border/20">
          <div
            className={cn(
              "h-full transition-all duration-300 ease-out",
              allVoted ? "bg-success" : "bg-primary",
            )}
            style={{ width: `${voteProgress * 100}%` }}
          />
        </div>
      )}

      {/* Candidate / target list */}
      <div className={cn("px-4 py-2.5 flex flex-wrap gap-2", !isBadgeSpeech && "border-b border-border/30")}>
        {isBadgeSpeech && candidates.map(cid => {
          const p = players.find(pl => pl.id === cid);
          const spoken = spokenSet.has(cid);
          const isSpeaking = activeSpeakerId === cid;
          return (
            <span key={cid} className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium border transition-all shadow-sm",
              isSpeaking && "border-success/40 bg-success/8 text-success ring-1 ring-success/20",
              spoken && !isSpeaking && "border-primary/25 bg-primary/6 text-primary",
              !spoken && !isSpeaking && "border-border/60 bg-cardBackground/50 text-text-sub/90",
            )}>
              {p ? `${p.seat}号 ${p.name}` : cid}
              {spoken && <span className="text-[10px] font-bold">✓</span>}
              {isSpeaking && <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />}
            </span>
          );
        })}

        {(isBadgeElection) && voteTally.size > 0 && (
          Array.from(voteTally.entries())
            .sort(([, a], [, b]) => b.count - a.count)
            .map(([tid, { count }], idx) => {
              const p = players.find(pl => pl.id === tid);
              const isPk = pkTargets.has(tid);
              const isLeading = tid === leadingId && leadingCount > 0 && idx === 0;
              return (
                <div
                  key={tid}
                  className="inline-flex items-center gap-1.5 min-h-[44px] px-3 py-1.5 rounded-lg border border-border/40 bg-background/50 text-xs"
                >
                  <span className="font-medium text-textPrimary">
                    {p ? `${p.seat}号 ${p.name}` : tid}
                  </span>
                  <span className="text-text-sub/50">→</span>
                  <span className={cn(
                    "font-medium text-accent",
                    isLeading && "font-bold",
                    isPk && "text-warning"
                  )}>
                    {count}{language === "zh" ? "票" : ""}
                    {isLeading && voteTally.size > 1 && <span className="ml-1 text-[10px] font-medium">领先</span>}
                  </span>
                </div>
              );
            })
        )}
      </div>

      {/* Unvoted / next-step hint */}
      {isBadgeSpeech && candidates.length > 0 && spokenSet.size < candidates.length && (
        <div className="mt-2.5 text-xs text-text-sub/70">
          {language === "zh" ? "全部发言完成后进入投票环节" : "Voting begins after all speeches"}
        </div>
      )}
      
      {/* 等待投票区域，和VotePanel统一 */}
      {(isBadgeElection) && !allVoted && (
        <div className="px-4 py-2 border-t border-border/20">
          <span className="text-[11px] text-text-sub/50">
            {language === "zh" ? "⏳ 等待投票: " : "⏳ Waiting: "}
          </span>
          <span className="text-[11px] text-text-sub/70">
            {players.filter(p => p.alive && !candidateSet.has(p.id) && !votedSet.has(p.id)).map(p => `${p.seat}号 ${p.name}`).join(" · ")}
          </span>
        </div>
      )}
      {(isBadgeElection) && allVoted && leadingCount > 0 && (
        <div className="px-4 py-2 border-t border-border/20 text-xs text-accent font-medium">
          {isBadgeElection
            ? (language === "zh" ? "投票完成，即将公布警长结果" : "Vote complete — sheriff result incoming")
            : (language === "zh" ? "投票完成，即将公布放逐结果" : "Vote complete — exile result incoming")}
        </div>
      )}
    </div>
  );
}
