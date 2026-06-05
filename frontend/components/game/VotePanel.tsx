"use client";

import React, { useMemo } from "react";
import { Language, Player } from "@/types";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface VotePanelProps {
  /** voter_id → target_id */
  votes: Record<string, string>;
  players: Player[];
  language: Language;
  phase: string;
}

/** Show during active voting phase: progress, vote cards, waiting list */
export function VotePanel({ votes, players, language, phase }: VotePanelProps) {
  const { alivePlayers, votedCount, totalVoters, percent, voteEntries, waitingPlayers } = useMemo(() => {
    const alive = players.filter((p) => p.alive);
    const ids = Object.keys(votes);
    const totalVoters = alive.length;
    const votedCount = ids.filter((vid) => alive.some((ap) => ap.id === vid)).length;
    const percent = totalVoters > 0 ? Math.round((votedCount / totalVoters) * 100) : 0;

    // Build vote relationship entries: voter → target
    const playerMap = new Map(players.map((p) => [p.id, p]));
    const entries: { voter: Player; target: Player | undefined }[] = [];
    for (const voterId of ids) {
      const voter = playerMap.get(voterId);
      if (!voter) continue;
      const targetId = votes[voterId];
      const target = targetId ? playerMap.get(targetId) : undefined;
      entries.push({ voter, target });
    }

    const waiting = alive.filter((p) => !ids.includes(p.id));
    return { alivePlayers: alive, votedCount, totalVoters, percent, voteEntries: entries, waitingPlayers: waiting };
  }, [votes, players]);

  // Phase label
  const isBadgeVote = phase.includes("BADGE") || phase.includes("ELECTION");
  const title = isBadgeVote
    ? (language === "zh" ? "警徽投票" : "Badge Vote")
    : (language === "zh" ? "投票放逐" : "Exile Vote");

  return (
    <div className="mx-4 mt-3 rounded-xl border border-border/50 bg-cardBackground/60 backdrop-blur-sm overflow-hidden">
      {/* ── Header + Progress ──────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/30">
        <div className="flex items-center gap-2">
          <span className="text-base">🗳</span>
          <span className="text-sm font-semibold text-textPrimary">{title}</span>
        </div>
        <span className="text-xs text-text-sub tabular-nums">
          {language === "zh" ? `已投 ${votedCount}/${totalVoters}` : `Voted ${votedCount}/${totalVoters}`}
        </span>
      </div>

      {/* ── Progress bar ────────────────────────────────── */}
      <div className="h-1 bg-border/20">
        <div
          className="h-full bg-primary transition-all duration-300 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>

      {/* ── Vote relationship cards ─────────────────────── */}
      {voteEntries.length > 0 && (
        <div className="px-4 py-2.5 flex flex-wrap gap-2">
          {voteEntries.map(({ voter, target }) => (
            <div
              key={voter.id}
              className="inline-flex items-center gap-1.5 min-h-[44px] px-3 py-1.5 rounded-lg border border-border/40 bg-background/50 text-xs"
            >
              <span className="font-medium text-textPrimary">
                {voter.seat}{language === "zh" ? "号" : ""} {voter.name}
              </span>
              <span className="text-text-sub/50">→</span>
              <span className={cn(
                "font-medium",
                target ? "text-accent" : "text-text-sub/40"
              )}>
                {target ? `${target.seat}${language === "zh" ? "号" : ""} ${target.name}` : (language === "zh" ? "弃权" : "Skip")}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* ── Waiting players ─────────────────────────────── */}
      {waitingPlayers.length > 0 && (
        <div className="px-4 py-2 border-t border-border/20">
          <span className="text-[11px] text-text-sub/50">
            {language === "zh" ? "⏳ 等待投票: " : "⏳ Waiting: "}
          </span>
          <span className="text-[11px] text-text-sub/70">
            {waitingPlayers.map((p) => `${p.seat}${language === "zh" ? "号" : ""} ${p.name}`).join(" · ")}
          </span>
        </div>
      )}
    </div>
  );
}
