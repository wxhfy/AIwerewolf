"use client";

import React, { useMemo } from "react";
import { Language, Player } from "@/types";
import { cn } from "@/lib/utils";

interface VotePanelProps {
  votes: Record<string, string>;
  players: Player[];
  language: Language;
  phase: string;
}

export function VotePanel({ votes, players, language, phase }: VotePanelProps) {
  const { votedCount, totalVoters, percent, voteEntries, waitingPlayers } = useMemo(() => {
    const alive = players.filter((p) => p.alive);
    const ids = Object.keys(votes);
    const totalVoters = alive.length;
    const votedCount = ids.filter((vid) => alive.some((ap) => ap.id === vid)).length;
    const percent = totalVoters > 0 ? Math.round((votedCount / totalVoters) * 100) : 0;

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
    return { votedCount, totalVoters, percent, voteEntries: entries, waitingPlayers: waiting };
  }, [votes, players]);

  const isBadgeVote = phase.includes("BADGE") || phase.includes("ELECTION");
  const title = isBadgeVote
    ? (language === "zh" ? "警徽投票" : "Badge Vote")
    : (language === "zh" ? "投票放逐" : "Exile Vote");
  const isZh = language === "zh";

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-cardBackground/95 shadow-float backdrop-blur" data-phase-aware>
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-accent/10">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-accent/15 text-base">🗳️</span>
          <span className="text-sm font-bold text-primary tracking-wide">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-base font-bold tabular-nums",
            votedCount === totalVoters ? "text-success" : "text-primary"
          )}>
            {votedCount}<span className="text-xs font-normal text-text-sub">/{totalVoters}</span>
          </span>
        </div>
      </div>

      {/* ── Progress bar ── */}
      <div className="h-1 bg-border/20">
        <div
          className={cn(
            "h-full transition-all duration-500 ease-out rounded-r-sm",
            percent >= 100 ? "bg-success" : "bg-primary"
          )}
          style={{ width: `${Math.max(percent, votedCount > 0 ? 3 : 0)}%` }}
        />
      </div>

      {/* ── Vote cards ── */}
      {voteEntries.length > 0 && (
        <div className="flex flex-wrap gap-2 px-4 py-2.5">
          {voteEntries.map(({ voter, target }) => (
            <div
              key={voter.id}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-background/70 px-2.5 py-1.5 text-xs font-medium"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-white">
                {voter.seat}
              </span>
              <span className="text-textPrimary">{voter.name}</span>
              <span className="mx-0.5 text-primary/50">→</span>
              {target ? (
                <>
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-danger text-[10px] font-bold text-white">
                    {target.seat}
                  </span>
                  <span className="font-semibold text-danger">{target.name}</span>
                </>
              ) : (
                <span className="text-text-sub italic">{isZh ? "弃权" : "Skip"}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Waiting players ── */}
      {waitingPlayers.length > 0 && (
        <div className="border-t border-border/40 bg-background/45 px-4 py-2">
          <span className="text-xs text-text-sub/70">{isZh ? "等待: " : "Waiting: "}</span>
          {waitingPlayers.map((p, i) => (
            <span key={p.id} className="text-xs text-text-sub">
              {i > 0 && " · "}
              <span className="mr-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-border/40 text-[10px] font-bold text-text-sub">{p.seat}</span>
              {p.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
