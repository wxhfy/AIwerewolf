"use client";

import { memo } from "react";
import { t } from "@/lib/i18n";
import { Language } from "@/types";

interface ThinkingBubbleProps {
  playerName: string;
  playerSeat: number;
  language: Language;
}

/**
 * AI 玩家正在组织发言时显示的占位气泡。
 * 当 pending_input 指示某玩家正在发言但 CHAT_MESSAGE 尚未到达时渲染。
 */
export const ThinkingBubble = memo(function ThinkingBubble({
  playerName,
  playerSeat,
  language,
}: ThinkingBubbleProps) {
  const avatarLetter = (playerName || "?").charAt(0);

  return (
    <div className="flex gap-2.5 py-2 animate-slide-in">
      {/* Avatar — 半透明表示等待中 */}
      <div className="w-10 h-10 rounded-full flex-shrink-0 flex items-center justify-center text-base font-bold bg-primary/10 text-primary/60">
        {avatarLetter}
      </div>

      {/* Bubble + meta */}
      <div className="flex flex-col max-w-[75%]">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-textPrimary">
            {playerSeat}号 {playerName}
          </span>
          <span className="text-xs text-text-sub/60">
            {t("playerSpeaking", language)}
          </span>
        </div>

        {/* 思考气泡 */}
        <div className="px-4 py-2.5 rounded-[4px_16px_16px_16px] bg-background text-text-sub/60 italic text-base">
          {t("organizingSpeech", language)}
          <span className="inline-flex ml-0.5">
            <span className="animate-dot-1">.</span>
            <span className="animate-dot-2">.</span>
            <span className="animate-dot-3">.</span>
          </span>
        </div>
      </div>
    </div>
  );
});
