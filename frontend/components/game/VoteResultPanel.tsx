"use client";

import React, { useMemo } from "react";
import { Language, Player } from "@/types";

interface VoteResultPanelProps {
  /** voter_id → target_id */
  votes: Record<string, string>;
  players: Player[];
  language: Language;
  /** Vote phase label (badge vs exile) */
  isBadgeVote?: boolean;
}

const BAR_COLORS = [
  "bg-primary",          // gold
  "bg-accent",           // amber
  "bg-info",             // blue
  "bg-[#a78bfa]",        // violet
  "bg-[#34d399]",        // emerald
  "bg-[#f87171]",        // red
  "bg-[#fbbf24]",        // yellow
  "bg-[#60a5fa]",        // sky
  "bg-[#fb923c]",        // orange
  "bg-[#a3e635]",        // lime
  "bg-[#e879f9]",        // fuchsia
  "bg-[#22d3ee]",        // cyan
];

/** Visual vote result card — inline in the narrative event flow */
export function VoteResultPanel({ votes, players, language, isBadgeVote = false }: VoteResultPanelProps) {
  const { candidates, maxVotes } = useMemo(() => {
    const tally = new Map<string, number>();
    const vmap = new Map<string, string[]>(); // targetId → voter labels
    const playerMap = new Map(players.map((p) => [p.id, p]));

    for (const [voterId, targetId] of Object.entries(votes)) {
      const voter = playerMap.get(voterId);
      if (!voter) continue;
      const voterLabel = `${voter.seat}${language === "zh" ? "号" : ""} ${voter.name}`;
      const key = targetId || "__skip__";
      if (!tally.has(key)) { tally.set(key, 0); vmap.set(key, []); }
      tally.set(key, tally.get(key)! + 1);
      vmap.get(key)!.push(voterLabel);
    }

    const list = Array.from(tally.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([id, count]) => ({
        id,
        count,
        voters: vmap.get(id) || [],
        player: id !== "__skip__" ? playerMap.get(id) : undefined,
        isSkip: id === "__skip__",
      }));

    return { candidates: list, maxVotes: Math.max(1, ...list.map((c) => c.count)) };
  }, [votes, players, language]);

  const title = isBadgeVote
    ? (language === "zh" ? "🗳 警徽投票结果" : "🗳 Badge Vote Result")
    : (language === "zh" ? "🗳 投票放逐结果" : "🗳 Exile Vote Result");

  const top = candidates[0];
  const exiled = top && !top.isSkip ? top.player : undefined;

  return (
    <div className="mt-3 mb-2 rounded-xl border border-border/40 bg-cardBackground/60 overflow-hidden animate-fade-in">
      {/* ── Header ─────────────────────────────────────── */}
      <div className="px-4 py-3 border-b border-border/20">
        <p className="text-sm font-semibold text-textPrimary">{title}</p>
      </div>

      {/* ── Bar chart rows ─────────────────────────────── */}
      <div className="px-4 py-3 space-y-2.5">
        {candidates.map((c, idx) => {
          const barWidth = Math.max(8, Math.round((c.count / maxVotes) * 100));
          const isMax = c.count === maxVotes && !c.isSkip;

          return (
            <div key={c.id} className="space-y-1">
              {/* Candidate name + vote count */}
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-medium text-textPrimary truncate">
                  {c.isSkip
                    ? (language === "zh" ? "弃权" : "Abstain")
                    : c.player
                    ? `${c.player.seat}${language === "zh" ? "号" : ""} · ${c.player.name}`
                    : "?"}
                </span>
                <span className={`text-xs font-bold tabular-nums shrink-0 ${isMax ? "text-primary" : "text-text-sub"}`}>
                  {c.count}{language === "zh" ? "票" : ""}
                </span>
              </div>

              {/* Bar */}
              <div className="h-5 w-full rounded-full bg-border/10 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ease-out ${BAR_COLORS[idx % BAR_COLORS.length]} ${isMax ? "opacity-100" : "opacity-60"}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>

              {/* Voters */}
              {c.voters.length > 0 && (
                <p className="text-[10px] text-text-sub/40 pl-1 truncate">
                  ← {c.voters.join(" · ")}
                </p>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Exile result ────────────────────────────────── */}
      {exiled && !isBadgeVote && (
        <div className="px-4 py-3 border-t border-border/20 bg-danger/5">
          <p className="text-sm text-danger font-semibold">
            🚫 {exiled.seat}{language === "zh" ? "号" : ""} {exiled.name}{" "}
            {language === "zh" ? "被放逐出局" : "is exiled"}
          </p>
        </div>
      )}
    </div>
  );
}
