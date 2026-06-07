"use client";

import { t } from "@/lib/i18n";
import { deriveStatusText } from "@/lib/deriveStatusText";
import { ViewMode, type GameState, type Language } from "@/types";
import type { useGameDerivedState } from "@/hooks/useGameDerivedState";

interface AIStatusBarProps {
  gameState: GameState | null;
  derived: ReturnType<typeof useGameDerivedState>;
  language: Language;
  viewMode: ViewMode;
}

export function AIStatusBar({ gameState, derived, language, viewMode }: AIStatusBarProps) {
  const isAudienceNight = viewMode === ViewMode.PUBLIC && Boolean(gameState?.phase?.startsWith("NIGHT_"));
  const { statusTitle, actionText } = isAudienceNight
    ? {
        statusTitle: language === "zh" ? "夜晚行动中" : "Night actions",
        actionText: language === "zh" ? "隐藏身份与夜间目标" : "roles and targets hidden",
      }
    : deriveStatusText(gameState, language, derived.speakerState);

  return (
    <div className="flex items-center gap-3 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium">
      <span className="font-semibold text-textPrimary">{statusTitle}</span>
      {actionText && (
        <span className="text-text-sub">
          · <span className="text-primary font-medium">{actionText}</span>
        </span>
      )}
      <span className="text-text-sub/60 ml-auto text-sm">
        {t("aliveCount", language)}: {derived.aliveCount}/{gameState?.players?.length || 0}
      </span>
    </div>
  );
}
