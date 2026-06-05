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
  selectedTarget: string;
  selectedPlayer: Player | undefined;
  setSelectedTarget: (id: string) => void;
  onSubmit: () => void;
  language: string;
}

export function HumanActionBar({
  pending,
  isSpeech,
  needsTarget,
  canSubmit,
  speech,
  setSpeech,
  selectedPlayer,
  setSelectedTarget,
  onSubmit,
  language,
}: HumanActionBarProps) {
  const lang = language as "zh" | "en";

  if (isSpeech) {
    return (
      <div className="border-t border-border bg-cardBackground px-4 py-2">
        <div className="flex items-end gap-2">
          <textarea
            value={speech}
            onChange={(e) => setSpeech(e.target.value)}
            placeholder={pending?.placeholder || (lang === "zh" ? "输入发言..." : "Type your speech...")}
            className="flex-1 h-20 resize-none rounded-lg border border-border bg-background px-3 py-3 text-sm text-textPrimary placeholder:text-text-sub/40"
          />
          <Button onClick={onSubmit} size="sm">
            {pending?.request === "BADGE_SPEECH"
              ? (lang === "zh" ? "提交竞选发言" : "Submit Speech")
              : pending?.request === "LAST_WORDS"
              ? (lang === "zh" ? "结束遗言" : "End Last Words")
              : (lang === "zh" ? "发送" : "Send")}
          </Button>
          {pending?.request === "BADGE_SPEECH" && (
            <button
              onClick={() => { setSpeech(""); onSubmit(); }}
              className="text-[11px] text-text-sub/60 hover:text-text-sub shrink-0"
            >
              {lang === "zh" ? "不竞选" : "Skip"}
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Target selection mode ──
  return (
    <div className="border-t border-border bg-cardBackground px-4 py-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-sub truncate">
          {pending?.prompt || (needsTarget
            ? (lang === "zh" ? "点击玩家卡片投票 / 轮到你了" : "Tap player cards to vote / Your turn")
            : "")}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {selectedPlayer && (
            <>
              <span className="text-xs text-primary font-medium">
                {lang === "zh" ? "你选择投票给" : "Voting for"}{" "}
                {selectedPlayer.seat}号 {selectedPlayer.name}
              </span>
              <button
                onClick={() => setSelectedTarget("")}
                className="text-[11px] text-text-sub/60 hover:text-text-sub"
              >
                {lang === "zh" ? "取消" : "Cancel"}
              </button>
            </>
          )}
          <Button onClick={onSubmit} disabled={!canSubmit} size="sm">
            {pending?.request === "DIVINE"
              ? (lang === "zh" ? "确认查验" : "Confirm Divine")
              : pending?.request === "ATTACK"
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
    </div>
  );
}

/** Submitted state indicator — shown after human submits, waiting for phase advance */
export function SubmittedIndicator({ language }: { language: string }) {
  return (
    <div className="border-t border-border bg-cardBackground px-4 py-2 flex items-center gap-2 text-xs text-text-sub">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
      {language === "zh" ? "已提交，等待阶段推进" : "Submitted, waiting for phase advance"}
    </div>
  );
}
