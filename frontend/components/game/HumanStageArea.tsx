"use client";

import React from "react";
import { Player } from "@/types";
import type { HumanDisplayState } from "@/hooks/useHumanDisplayState";

interface HumanStageAreaProps {
  display: HumanDisplayState;
  players: Player[];
  votes: Record<string, string>;
}

const NIGHT_ICONS: Record<string, string> = {
  NIGHT_START: "🌙", NIGHT_GUARD_ACTION: "🛡️", NIGHT_WOLF_ACTION: "🐺",
  NIGHT_WITCH_ACTION: "🧪", NIGHT_SEER_ACTION: "🔮", NIGHT_RESOLVE: "🌅",
};

const StagePlaceholder = () => (
  <div className="flex items-center justify-center py-20">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
  </div>
);

export const HumanStageArea = React.memo(function HumanStageArea({ display, players, votes }: HumanStageAreaProps) {
  const d = display;
  if (!d.phase) return <StagePlaceholder />;

  const p = d.phase;
  const icon = d.isNight ? (NIGHT_ICONS[p] || "🌙") : p.includes("SPEECH") ? "🗣️" : p.includes("VOTE") ? "🗳️" : d.isOver ? "🏆" : "☀️";

  return (
    <div className="px-5 py-6">
      {/* Icon + brief hint only — phase title is in top bar */}
      <div className="text-center">
        <p className="text-5xl mb-3">{icon}</p>
        {d.isMyTurn && d.canAct && <p className="text-sm text-success font-medium animate-pulse">⚡ 轮到你了</p>}
        {!d.isMyTurn && d.isNight && <p className="text-sm text-text-sub/60">等待中...</p>}
        {d.isOver && <p className="text-xl font-bold text-textPrimary">{d.phaseLabel}</p>}
      </div>

      {/* Vote result */}
      {d.voteResultMsg && (p === "DAY_LAST_WORDS" || p === "DAY_RESOLVE" || p === "NIGHT_START") && (
        <div className="rounded-card border-2 border-danger/20 bg-danger/5 px-4 py-3 mt-4 text-center">
          <p className="text-xs text-text-sub mb-1">投票结果</p>
          <p className="text-base font-bold text-danger">{d.voteResultMsg}</p>
        </div>
      )}

      {/* Death results */}
      {d.deathNames.length > 0 && p === "DAY_START" && (
        <div className="rounded-card border-2 border-danger/20 bg-danger/5 px-4 py-3 mt-4 text-center">
          <p className="text-xs text-text-sub mb-1">天亮结算</p>
          {d.deathNames.map((name, i) => <p key={i} className="text-base font-bold text-danger">{name} 死亡</p>)}
        </div>
      )}

      <p className="text-center text-xs text-text-sub/50 mt-4">存活 {d.aliveCount}/{d.totalCount} 人</p>
    </div>
  );
});
