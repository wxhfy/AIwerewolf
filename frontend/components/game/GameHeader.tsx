"use client";

import { Language } from "@/types";
import { format, t } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { BackgroundMusic } from "@/components/game/BackgroundMusic";

interface GameHeaderProps {
  roomId: string;
  day?: number;
  winner?: string;
  language: Language;
  isVisualNight: boolean;
  isHumanMode: boolean;
  isPlaying: boolean;
  isPaused: boolean;
  canRun: boolean;
  onRun: () => void;
  onStartHuman: () => void;
  onPause: () => void;
  onResume: () => void;
}

export function GameHeader({
  roomId,
  day,
  winner,
  language,
  isVisualNight,
  isHumanMode,
  isPlaying,
  isPaused,
  canRun,
  onRun,
  onStartHuman,
  onPause,
  onResume,
}: GameHeaderProps) {
  const canControlAiGame = !isHumanMode && !winner;

  return (
    <header className="relative z-10 grid shrink-0 grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2 border-b border-border bg-cardBackground px-3 py-2.5 sm:gap-4 md:px-6 [@media(max-height:500px)]:py-1.5" data-phase-aware>
      <div className="min-w-0">
        <p className="truncate font-display text-sm font-semibold tracking-wide text-primary sm:text-base">AI Werewolf</p>
        <p className="truncate text-[10px] text-text-sub sm:text-xs" title={roomId}>{t("roomLabel", language)} · {truncate(roomId, 8)}</p>
      </div>
      <div className="flex min-w-0 items-center gap-2 rounded-button border border-border bg-background px-2.5 py-1.5 sm:px-3">
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
          className={isVisualNight ? "text-primary" : "text-accent"}>
          {isVisualNight ? <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /> :
            <><circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" /></>}
        </svg>
        <span className="whitespace-nowrap font-display text-xs font-semibold text-textPrimary sm:text-sm">
          {day ? format(t("dayNumber", language), { day }) : t("statusReady", language)}
          {winner && <span className="ml-2 hidden text-accent sm:inline">{t("gameOver", language)}</span>}
        </span>
      </div>
      <div className="flex items-center justify-end gap-2">
        <div className="hidden items-center text-xs text-text-sub lg:flex">
          {isHumanMode
            ? language === Language.ZH ? "玩家视角" : "Player view"
            : language === Language.ZH ? "AI 对战" : "AI match"}
        </div>
        {canControlAiGame && (isPlaying || isPaused) && (
          <Button
            data-testid="global-pause-toggle"
            size="sm"
            variant="secondary"
            onClick={isPaused ? onResume : onPause}
            aria-pressed={isPaused}
          >
            {isPaused
              ? (language === Language.ZH ? "继续" : "Resume")
              : (language === Language.ZH ? "暂停" : "Pause")}
          </Button>
        )}
        {canRun && !isHumanMode && <Button size="sm" onClick={onRun}>{t("run", language)}</Button>}
        {canRun && isHumanMode && <Button size="sm" onClick={onStartHuman}>{t("run", language)}</Button>}
        <BackgroundMusic language={language} placement="inline" />
      </div>
    </header>
  );
}
