"use client";

import { memo } from "react";
import { t } from "@/lib/i18n";
import { Language } from "@/types";
import { SpeechCard } from "@/components/game/_speech/SpeechCard";

interface ThinkingBubbleProps {
  playerName: string;
  playerSeat: number;
  language: Language;
}

/** AI 玩家正在组织发言 — 与 ChatBubble 共用 SpeechCard 骨架。 */
export const ThinkingBubble = memo(function ThinkingBubble({
  playerName,
  playerSeat,
  language,
}: ThinkingBubbleProps) {
  return (
    <SpeechCard
      seat={playerSeat}
      name={playerName}
      headerRight={t("playerSpeaking", language)}
    >
      <span className="text-text-sub/50 italic">
        {t("organizingSpeech", language)}
        <span className="inline-flex ml-0.5">
          <span className="animate-dot-1">.</span>
          <span className="animate-dot-2">.</span>
          <span className="animate-dot-3">.</span>
        </span>
      </span>
    </SpeechCard>
  );
});
