"use client";

import { Language, ViewMode } from "@/types";
import { format, t } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

interface GameHeaderProps {
  roomId: string;
  day?: number;
  winner?: string;
  language: Language;
  viewMode: ViewMode;
  isVisualNight: boolean;
  isHumanMode: boolean;
  canRun: boolean;
  onRun: () => void;
  onStartHuman: () => void;
  onViewModeChange: (mode: ViewMode) => void;
  onLanguageChange: (language: Language) => void;
}

export function GameHeader({
  roomId,
  day,
  winner,
  language,
  viewMode,
  isVisualNight,
  isHumanMode,
  canRun,
  onRun,
  onStartHuman,
  onViewModeChange,
  onLanguageChange,
}: GameHeaderProps) {
  return (
    <header className="relative z-10 flex flex-wrap items-center gap-3 border-b border-border bg-cardBackground px-4 py-2.5 md:px-6" data-phase-aware>
      <div className="flex items-center gap-3">
        <span className="font-display text-lg font-semibold text-primary">AI Werewolf</span>
        <span className="text-xs text-text-sub">{t("roomLabel", language)}: {truncate(roomId, 8)}</span>
      </div>
      <div className="mx-auto flex items-center gap-2">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
          className={isVisualNight ? "text-primary" : "text-accent"}>
          {isVisualNight ? <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /> :
            <><circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" /></>}
        </svg>
        <span className="font-display text-lg font-bold text-textPrimary">
          {day ? format(t("dayNumber", language), { day }) : t("statusReady", language)}
          {winner && <span className="ml-2 text-accent"> - {winner === "village" ? t("village", language) : t("wolf", language)}</span>}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex overflow-hidden rounded-button border border-border">
          <button onClick={() => onViewModeChange(ViewMode.PUBLIC)} className={`px-2 py-1 text-xs font-medium ${viewMode === ViewMode.PUBLIC ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>{t("public", language)}</button>
          <button onClick={() => onViewModeChange(ViewMode.MODERATOR)} className={`px-2 py-1 text-xs font-medium ${viewMode === ViewMode.MODERATOR ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>{t("private", language)}</button>
        </div>
        {canRun && !isHumanMode && <Button size="sm" onClick={onRun}>{t("run", language)}</Button>}
        {canRun && isHumanMode && <Button size="sm" onClick={onStartHuman}>{t("run", language)}</Button>}
        <div className="flex overflow-hidden rounded-button border border-border">
          <button onClick={() => onLanguageChange(Language.ZH)} className={`px-2 py-1 text-xs font-medium ${language === Language.ZH ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>中</button>
          <button onClick={() => onLanguageChange(Language.EN)} className={`px-2 py-1 text-xs font-medium ${language === Language.EN ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>EN</button>
        </div>
      </div>
    </header>
  );
}
