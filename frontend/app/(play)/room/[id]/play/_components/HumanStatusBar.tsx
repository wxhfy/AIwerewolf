"use client";

import { t, tPhase } from "@/lib/i18n";
import { Language } from "@/types";
import type { HumanDisplayState } from "@/hooks/useHumanDisplayState";

const PHASE_LABEL: Record<string, string> = {
  SETUP: "准备阶段", NIGHT_START: "夜幕降临", NIGHT_GUARD_ACTION: "守卫行动",
  NIGHT_WOLF_ACTION: "狼人行动", NIGHT_WITCH_ACTION: "女巫行动", NIGHT_SEER_ACTION: "预言家行动",
  NIGHT_RESOLVE: "夜晚结算", DAY_START: "天亮了", DAY_BADGE_SIGNUP: "警徽报名",
  DAY_BADGE_SPEECH: "警徽竞选发言", DAY_BADGE_ELECTION: "警徽投票",
  DAY_PK_SPEECH: "PK 发言", DAY_SPEECH: "自由发言", DAY_SHERIFF_CLOSING: "警长归票", DAY_VOTE: "投票放逐",
  DAY_LAST_WORDS: "遗言", DAY_RESOLVE: "白天结算", HUNTER_SHOOT: "猎人开枪",
  BADGE_TRANSFER: "警徽移交", GAME_END: "游戏结束",
};

interface HumanStatusBarProps {
  display: HumanDisplayState;
  displayPhase?: string;
  language: string;
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
  players?: Array<{ id: string; seat: number; name: string }>;
  runtimeProgress?: {
    current?: Array<{ seat: number; name: string }>;
    queue?: Array<{ seat: number; name: string }>;
    remaining_count?: number;
    estimated_wait_seconds?: number | null;
    simultaneous?: boolean;
    thinking_count?: number;
  } | null;
}

export function HumanStatusBar({ display, displayPhase, language, speakerState, runtimeProgress }: HumanStatusBarProps) {
  const visiblePhase = displayPhase || display.phase;
  const lang = language === "en" ? Language.EN : Language.ZH;
  const phaseLabel = lang === Language.ZH
    ? PHASE_LABEL[visiblePhase] || visiblePhase
    : tPhase(visiblePhase, lang);
  const progressCurrent = runtimeProgress?.current?.[0];
  const remaining = Number(runtimeProgress?.remaining_count ?? runtimeProgress?.queue?.length ?? 0);
  const eta = runtimeProgress?.estimated_wait_seconds;

  return (
    <div data-testid="human-status-bar" className="shrink-0 space-y-2 border-b border-border bg-cardBackground px-3 py-3 sm:px-5" data-phase-aware>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0" role="status" aria-live="polite">
          <p className={display.currentActor ? "mb-0.5 text-xs text-text-sub" : "text-sm font-semibold text-textPrimary"}>
            {phaseLabel || (lang === "zh" ? "等待对局就绪" : "Waiting for the match")}
          </p>
          {display.currentActor && (
            <p className={`text-sm font-semibold leading-relaxed ${display.canAct ? "text-primary" : "text-textPrimary"}`}>
              {lang === "zh" ? `${display.currentActor.seat}号` : `#${display.currentActor.seat}`} {display.currentActor.name}{" "}
              {display.currentActor.seat === display.mySeat
                ? display.canAct
                  ? lang === "zh" ? "· 轮到你了" : "· Your turn"
                  : ""
                : speakerState?.speakerId === display.currentActor.id && speakerState.state !== "finished"
                  ? lang === "zh"
                    ? speakerState.state === "thinking" ? "· 思考中" : "· 发言中"
                    : speakerState.state === "thinking" ? "· Thinking" : "· Speaking"
                  : lang === "zh" ? "· 行动中" : "· Acting"}
            </p>
          )}
        </div>
        <span className="shrink-0 rounded-badge border border-border bg-background px-2.5 py-1 text-xs tabular-nums text-text-sub">
          {t("aliveCount", lang)} <strong className="font-semibold text-textPrimary">{display.aliveCount}/{display.totalCount}</strong>
        </span>
      </div>
      {!display.canAct && (progressCurrent || remaining > 0) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border pt-2 text-xs text-text-sub">
          {progressCurrent && (
            <span className="inline-flex items-center gap-1.5 text-primary">
              <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              {progressCurrent.seat ? `${lang === "zh" ? `${progressCurrent.seat}号` : `#${progressCurrent.seat}`} ${progressCurrent.name}` : progressCurrent.name}{" "}
              {lang === "zh" ? "思考中" : "thinking"}
            </span>
          )}
          {remaining > 0 && <span>{lang === "zh" ? `队列剩余 ${remaining}` : `${remaining} left in queue`}</span>}
          {typeof eta === "number" && eta > 0 && (
            <span className="ml-auto tabular-nums">{lang === "zh" ? `约 ${Math.ceil(eta)}s` : `~${Math.ceil(eta)}s`}</span>
          )}
        </div>
      )}
    </div>
  );
}
