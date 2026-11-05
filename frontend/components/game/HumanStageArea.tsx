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
  <div role="status" className="flex flex-col items-center justify-center gap-3 px-4 py-10 text-sm text-text-sub">
    <span aria-hidden="true" className="h-6 w-6 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
    <p>正在同步对局状态…</p>
  </div>
);

export const HumanStageArea = React.memo(function HumanStageArea({ display }: HumanStageAreaProps) {
  const d = display;
  if (!d.phase) return <StagePlaceholder />;

  const p = d.phase;
  const icon = d.isNight ? (NIGHT_ICONS[p] || "🌙") : p.includes("SPEECH") ? "🗣️" : p.includes("VOTE") ? "🗳️" : d.isOver ? "🏆" : "☀️";

  return (
    <section className="mx-auto w-full max-w-lg px-4 py-5 sm:py-6" aria-label={d.phaseLabel} data-testid="human-stage-area">
      <div className="text-center">
        <span aria-hidden="true" className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-card border border-border bg-primary/5 text-3xl">{icon}</span>
        {d.isMyTurn && d.canAct && <p className="text-sm font-semibold text-primary">轮到你行动</p>}
        {!d.isMyTurn && d.isNight && <p className="text-sm text-text-sub">等待其他玩家行动…</p>}
        {d.isOver && <p className="font-display text-xl font-semibold text-textPrimary">{d.phaseLabel}</p>}
      </div>

      {d.voteResultMsg && (p === "DAY_LAST_WORDS" || p === "DAY_RESOLVE" || p === "NIGHT_START") && (
        <div className="mt-4 rounded-card border border-danger/20 bg-danger/5 px-4 py-3 text-center">
          <p className="mb-1 text-xs text-text-sub">投票结果</p>
          <p className="text-sm font-semibold leading-relaxed text-danger">{d.voteResultMsg}</p>
        </div>
      )}

      {d.deathNames.length > 0 && p === "DAY_START" && (
        <div className="mt-4 rounded-card border border-danger/20 bg-danger/5 px-4 py-3 text-center">
          <p className="mb-1 text-xs text-text-sub">天亮结算</p>
          {d.deathNames.map((name, i) => <p key={i} className="text-sm font-semibold leading-relaxed text-danger">{name} 死亡</p>)}
        </div>
      )}

      <p className="mt-4 text-center text-xs tabular-nums text-text-sub">存活 {d.aliveCount} / {d.totalCount} 人</p>
    </section>
  );
});
