"use client";

import { Language } from "@/types";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

interface LobbyConfigCardProps {
  language: Language; playerCount: number; mode: "ai" | "human";
  humanSeat: number; isCreating: boolean; error: string;
  onPlayerCountChange: (value: number) => void;
  onModeChange: (mode: "ai" | "human") => void;
  onHumanSeatChange: (seat: number) => void;
  onCreateRoom: () => void;
}

export function LobbyConfigCard(props: LobbyConfigCardProps) {
  const { language, playerCount, mode, humanSeat, isCreating, error,
    onPlayerCountChange, onModeChange, onHumanSeatChange, onCreateRoom } = props;

  const isAi = mode === "ai";
  const modeDesc = isAi
    ? (language === "zh" ? "所有玩家由 AI 控制，以全局视角观看完整对局。" : "All players are AI-controlled. Watch the full match from a global view.")
    : (language === "zh" ? "选择一个座位亲自参与，其余玩家由 AI 扮演。" : "Pick a seat to join. Other players are AI-controlled.");
  const buttonText = isAi
    ? (language === "zh" ? "创建 AI 对局" : "Create AI Match")
    : (language === "zh" ? "创建真人参与对局" : "Create Human Match");
  const selectionStyles = "min-h-11 rounded-button border text-sm font-medium transition-[background-color,border-color,color,transform] duration-200 active:scale-[0.98] disabled:cursor-wait disabled:opacity-60";
  const selectedStyles = "border-primary/50 bg-primary/10 text-primary shadow-sm";
  const idleStyles = "border-border bg-background/60 text-textSecondary hover:border-primary/40 hover:bg-primary/5 hover:text-textPrimary";

  return (
    <Card className="w-full overflow-hidden shadow-float" aria-busy={isCreating}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-7 sm:py-5">
        <div>
          <h2 className="font-display text-lg font-semibold text-textPrimary">
            {language === "zh" ? "创建新对局" : "Create a match"}
          </h2>
          <p className="mt-1 text-xs leading-relaxed text-textSecondary">
            {language === "zh" ? "选择模式与人数，准备落座。" : "Choose your mode and take a seat."}
          </p>
        </div>
        <span className="rounded-badge border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium tabular-nums text-primary">
          {playerCount} {language === "zh" ? "人局" : "players"}
        </span>
      </div>

      <div className="space-y-6 p-5 sm:p-7">
        <fieldset disabled={isCreating} aria-describedby="lobby-mode-description">
          <legend className="mb-3 text-sm font-medium text-textPrimary">{t("gameMode", language)}</legend>
          <div className="grid grid-cols-2 gap-2 rounded-card bg-background/60 p-1.5">
            {(["ai", "human"] as const).map((m) => (
              <button key={m} type="button" data-testid={`mode-${m}-button`} onClick={() => onModeChange(m)}
                aria-pressed={mode === m}
                className={`${selectionStyles} px-2 py-2.5 ${
                  mode === m ? "border-primary/40 bg-cardBackground text-primary shadow-card" : "border-transparent text-textSecondary hover:bg-cardBackground/60 hover:text-textPrimary"
                }`}>
                {m === "ai" ? t("aiVsAi", language) : t("humanPlay", language)}
              </button>
            ))}
          </div>
          <p id="lobby-mode-description" className="mt-3 min-h-[3em] text-xs leading-relaxed text-textSecondary">{modeDesc}</p>
        </fieldset>

        <fieldset disabled={isCreating}>
          <legend className="mb-3 text-sm font-medium text-textPrimary">{t("playerCount", language)}</legend>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {[7, 8, 9, 10, 11, 12].map((count) => (
              <button key={count} type="button" onClick={() => onPlayerCountChange(count)}
                aria-pressed={playerCount === count}
                aria-label={language === "zh" ? `${count} 人局` : `${count} players`}
                className={`${selectionStyles} tabular-nums ${playerCount === count ? selectedStyles : idleStyles}`}>
                {count}
              </button>
            ))}
          </div>
        </fieldset>

        {/* Hidden mode controls are unmounted so they cannot receive keyboard focus. */}
        {!isAi && <fieldset disabled={isCreating} className="animate-scale-in border-t border-border pt-5">
          <legend className="sr-only">{t("yourSeat", language)}</legend>
          <p className="mb-3 flex items-center justify-between gap-2 text-sm font-medium text-textPrimary" aria-hidden="true">
            {t("yourSeat", language)}
            <span className="text-xs font-normal text-primary">{humanSeat} {language === "zh" ? "号位" : "seat"}</span>
          </p>
          <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {Array.from({ length: playerCount }, (_, i) => i + 1).map((seat) => (
              <button key={seat} type="button" onClick={() => onHumanSeatChange(seat)}
                data-testid={`human-seat-${seat}-button`}
                aria-pressed={humanSeat === seat}
                aria-label={language === "zh" ? `${seat} 号位` : `Seat ${seat}`}
                className={`${selectionStyles} tabular-nums ${humanSeat === seat ? selectedStyles : idleStyles}`}>
                {seat}
              </button>
            ))}
          </div>
        </fieldset>}

        {error && <div role="alert" className="rounded-card border border-danger/25 bg-danger/10 px-4 py-3 text-sm leading-relaxed text-danger">{error}</div>}

        <div className="space-y-3 border-t border-border pt-5">
          <Button onClick={onCreateRoom} loading={isCreating} size="lg" className="w-full font-semibold">
            {isCreating ? t("creating", language) : buttonText}
          </Button>
          <p role="status" className="text-center text-xs leading-relaxed text-textSecondary">
            {isCreating
              ? language === "zh" ? "正在准备玩家与席位，请稍候…" : "Preparing players and seats. One moment…"
              : language === "zh" ? "创建后可确认对局配置，再正式开始。" : "Review your setup before the match begins."}
          </p>
        </div>
      </div>
    </Card>
  );
}
