"use client";

import React, { useMemo } from "react";
import { Language, Player } from "@/types";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface VotePanelProps {
  votes: Record<string, string>;
  players: Player[];
  language: Language;
  phase: string;
}

export function VotePanel({ votes, players, language, phase }: VotePanelProps) {
  const { alivePlayers, votedCount, totalVoters, percent, voteEntries, waitingPlayers } = useMemo(() => {
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
    return { alivePlayers: alive, votedCount, totalVoters, percent, voteEntries: entries, waitingPlayers: waiting };
  }, [votes, players]);

  const isBadgeVote = phase.includes("BADGE") || phase.includes("ELECTION");
  const title = isBadgeVote
    ? (language === "zh" ? "警徽投票" : "Badge Vote")
    : (language === "zh" ? "投票放逐" : "Exile Vote");
  const isZh = language === "zh";

  return (
    <div className="mx-4 mt-3 rounded-2xl bg-white/95 shadow-xl shadow-black/10 overflow-hidden">
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-5 py-3.5 bg-accent/8">
        <div className="flex items-center gap-2.5">
          <span className="text-xl">🗳️</span>
          <span className="text-base font-bold text-accent tracking-wide">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn(
            "text-lg font-bold tabular-nums",
            votedCount === totalVoters ? "text-emerald-600" : "text-accent"
          )}>
            {votedCount}<span className="text-sm font-normal text-gray-400">/{totalVoters}</span>
          </span>
        </div>
      </div>

      {/* ── Progress bar ── */}
      <div className="h-1.5 bg-gray-100">
        <div
          className={cn(
            "h-full transition-all duration-500 ease-out rounded-r-sm",
            percent >= 100 ? "bg-emerald-500" : "bg-accent"
          )}
          style={{ width: `${Math.max(percent, votedCount > 0 ? 3 : 0)}%` }}
        />
      </div>

      {/* ── Vote cards ── */}
      {voteEntries.length > 0 && (
        <div className="px-5 py-3.5 flex flex-wrap gap-2.5">
          {voteEntries.map(({ voter, target }) => (
            <div
              key={voter.id}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-accent/8 text-sm font-medium shadow-sm"
            >
              <span className="flex items-center justify-center w-7 h-7 rounded-full bg-accent text-white text-xs font-bold shadow">
                {voter.seat}
              </span>
              <span className="text-gray-800">{voter.name}</span>
              <span className="text-accent/50 mx-0.5">→</span>
              {target ? (
                <>
                  <span className="flex items-center justify-center w-7 h-7 rounded-full bg-red-500 text-white text-xs font-bold shadow">
                    {target.seat}
                  </span>
                  <span className="text-red-600 font-semibold">{target.name}</span>
                </>
              ) : (
                <span className="text-gray-400 italic text-xs">{isZh ? "弃权" : "Skip"}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Waiting players ── */}
      {waitingPlayers.length > 0 && (
        <div className="px-5 py-2.5 bg-gray-50/80">
          <span className="text-xs text-gray-400">{isZh ? "⏳ 等待: " : "⏳ Waiting: "}</span>
          {waitingPlayers.map((p, i) => (
            <span key={p.id} className="text-xs text-gray-500">
              {i > 0 && " · "}
              <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-gray-200 text-[10px] font-bold mr-0.5 text-gray-500">{p.seat}</span>
              {p.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
