"use client";

import { Button } from "@/components/ui/Button";
import type { Player, PendingInput } from "@/types";

interface HumanActionBarProps {
  pending: PendingInput | null | undefined;
  isSpeech: boolean;
  needsTarget: boolean;
  canSubmit: boolean;
  speech: string;
  setSpeech: (s: string) => void;
  savePotion: boolean;
  setSavePotion: (v: boolean) => void;
  selectedTarget: string;
  selectedPlayer: Player | undefined;
  setSelectedTarget: (id: string) => void;
  onSubmit: () => void;
  onSkip: () => void;
  language: string;
}

export function HumanActionBar({
  pending,
  isSpeech,
  needsTarget,
  canSubmit,
  speech,
  setSpeech,
  savePotion,
  setSavePotion,
  selectedPlayer,
  setSelectedTarget,
  onSubmit,
  onSkip,
  language,
}: HumanActionBarProps) {
  const lang = language as "zh" | "en";
  const shellClass = "timeline-scroll relative z-10 max-h-[36dvh] shrink-0 overflow-y-auto overscroll-contain border-t border-primary/20 bg-cardBackground px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-4";

  if (isSpeech) {
    return (
      <section className={shellClass} aria-label={lang === "zh" ? "你的发言" : "Your speech"} data-testid="human-action-bar">
        <div className="mx-auto flex max-w-4xl flex-col gap-2 sm:flex-row sm:items-end sm:gap-3">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block text-xs font-medium text-primary">
              {lang === "zh" ? "轮到你发言" : "Your turn to speak"}
            </span>
            <textarea
              data-testid="human-speech-input"
              value={speech}
              onChange={(e) => setSpeech(e.target.value)}
              placeholder={pending?.placeholder || (lang === "zh" ? "输入发言..." : "Type your speech...")}
              className="block h-16 w-full resize-none rounded-button border border-border bg-background px-3 py-2 text-sm leading-relaxed text-textPrimary placeholder:text-text-sub sm:h-20 [@media(max-height:500px)]:h-14"
            />
          </label>
          <div className="flex shrink-0 items-center justify-end gap-2">
            {pending?.request === "BADGE_SPEECH" && (
              <Button
                variant="ghost"
                data-testid="human-skip-button"
                onClick={() => { setSpeech(""); onSubmit(); }}
                size="sm"
              >
                {lang === "zh" ? "不竞选" : "Skip"}
              </Button>
            )}
            <Button data-testid="human-submit-button" onClick={onSubmit} size="sm">
              {pending?.request === "BADGE_SPEECH"
                ? (lang === "zh" ? "提交竞选发言" : "Submit Speech")
                : pending?.request === "LAST_WORDS"
                ? (lang === "zh" ? "结束遗言" : "End Last Words")
                : (lang === "zh" ? "发送发言" : "Send")}
            </Button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className={shellClass} aria-label={lang === "zh" ? "你的行动" : "Your action"} data-testid="human-action-bar">
      <div className="mx-auto flex max-w-4xl flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <p className="break-words text-xs leading-relaxed text-text-sub">
            {pending?.prompt || (needsTarget
              ? (lang === "zh" ? "点击玩家卡片选择合法目标" : "Tap a legal player card")
              : "")}
          </p>
          {pending?.request === "WITCH" && (
            <label className="mt-2 inline-flex cursor-pointer items-center gap-2 text-sm text-textPrimary">
              <input
                type="checkbox"
                checked={savePotion}
                onChange={(e) => setSavePotion(e.target.checked)}
                className="h-4 w-4 shrink-0 rounded accent-primary"
              />
              {lang === "zh" ? "使用解药救人" : "Use antidote"}
            </label>
          )}
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2 sm:max-w-[65%]">
          {selectedPlayer ? (
            <div className="mr-auto flex min-w-0 items-center gap-1.5 rounded-button bg-primary/5 pl-2 sm:mr-0">
              <span className="min-w-0 break-words text-xs font-medium text-primary">
                {lang === "zh" ? "已选择" : "Selected"} {selectedPlayer.seat}{lang === "zh" ? "号" : ""} {selectedPlayer.name}
              </span>
              <Button variant="ghost" onClick={() => setSelectedTarget("")} size="sm" className="shrink-0 px-2">
                {lang === "zh" ? "取消" : "Cancel"}
              </Button>
            </div>
          ) : (
            <span className="mr-auto text-xs text-text-sub sm:mr-0">
              {pending?.can_skip ? (lang === "zh" ? "可跳过" : "Skippable") : (lang === "zh" ? "未选择目标" : "No target")}
            </span>
          )}
          {pending?.can_skip && (
            <Button
              variant="ghost"
              size="sm"
              data-testid="human-skip-button"
              onClick={() => { setSelectedTarget(""); onSkip(); }}
            >
              {lang === "zh" ? "跳过" : "Skip"}
            </Button>
          )}
          <Button data-testid="human-submit-button" onClick={onSubmit} disabled={!canSubmit} size="sm" className="shrink-0">
            {pending?.request === "DIVINE"
              ? (lang === "zh" ? "确认查验" : "Confirm Divine")
              : pending?.request === "ATTACK" || pending?.request === "WOLF_TEAM_VOTE"
              ? (lang === "zh" ? "确认击杀" : "Confirm Attack")
              : pending?.request === "GUARD"
              ? (lang === "zh" ? "确认守护" : "Confirm Guard")
              : pending?.request === "WITCH"
              ? (lang === "zh" ? "确认用药" : "Confirm")
              : pending?.request === "SHOOT"
              ? (lang === "zh" ? "确认开枪" : "Confirm Shoot")
              : pending?.action_type === "vote"
              ? (lang === "zh" ? "确认投票" : "Confirm Vote")
              : (lang === "zh" ? "确认" : "Confirm")}
          </Button>
        </div>
      </div>
    </section>
  );
}

/** Submitted state indicator — shown after human submits, waiting for phase advance. */
export function SubmittedIndicator({ language }: { language: string }) {
  return (
    <div role="status" data-testid="human-submitted-indicator" className="relative z-10 flex shrink-0 items-center justify-center gap-2 border-t border-border bg-cardBackground px-3 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] text-xs text-text-sub">
      <span aria-hidden="true" className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
      {language === "zh" ? "已提交，等待其他玩家行动" : "Submitted, waiting for other players"}
    </div>
  );
}
