"use client";

import { t } from "@/lib/i18n";
import type { HumanDisplayState } from "@/hooks/useHumanDisplayState";

const PHASE_LABEL: Record<string, string> = {
  SETUP: "准备阶段", NIGHT_START: "夜幕降临", NIGHT_GUARD_ACTION: "守卫行动",
  NIGHT_WOLF_ACTION: "狼人行动", NIGHT_WITCH_ACTION: "女巫行动", NIGHT_SEER_ACTION: "预言家行动",
  NIGHT_RESOLVE: "夜晚结算", DAY_START: "天亮了", DAY_BADGE_SIGNUP: "警徽报名",
  DAY_BADGE_SPEECH: "警徽竞选发言", DAY_BADGE_ELECTION: "警徽投票",
  DAY_PK_SPEECH: "PK 发言", DAY_SPEECH: "自由发言", DAY_VOTE: "投票放逐",
  DAY_LAST_WORDS: "遗言", DAY_RESOLVE: "白天结算", HUNTER_SHOOT: "猎人开枪",
  BADGE_TRANSFER: "警徽移交", GAME_END: "游戏结束",
};

interface HumanStatusBarProps {
  display: HumanDisplayState;
  displayPhase?: string;
  language: string;
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
  players?: Array<{ id: string; seat: number; name: string }>;
}

export function HumanStatusBar({ display, displayPhase, language }: HumanStatusBarProps) {
  const visiblePhase = displayPhase || display.phase;
  const phaseLabel = PHASE_LABEL[visiblePhase] || visiblePhase;
  const lang = language as "zh" | "en";

  return (
    <div className="flex items-center gap-3 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium">
      <span className="font-semibold text-textPrimary">
        {display.cycle} · {phaseLabel}
      </span>
      {display.currentActor && (
        <span className="text-text-sub">
          ·{" "}
          <span className="text-primary font-medium">
            {display.currentActor.seat}号 {display.currentActor.name}{" "}
            {display.currentActor.name === display.myName
              ? display.canAct
                ? lang === "zh" ? "轮到你了" : "Your turn"
                : ""
              : speakerState?.speakerId === display.currentActor.id && speakerState.state !== "finished"
                ? lang === "zh" 
                  ? speakerState.state === "thinking" ? "思考中" : "发言中"
                  : speakerState.state === "thinking" ? "thinking" : "speaking"
                : lang === "zh" ? "行动中" : "acting"}
          </span>
        </span>
      )}
      <span className="text-text-sub/60 ml-auto text-sm">
        {t("aliveCount", lang as any)}: {display.aliveCount}/{display.totalCount}
      </span>
    </div>
  );
}
