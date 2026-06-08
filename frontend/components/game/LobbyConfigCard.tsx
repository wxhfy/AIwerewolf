"use client";

import { Language } from "@/types";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

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
    ? (language === "zh" ? "所有玩家由 AI 控制，你可以观战完整对局。" : "All players controlled by AI. Spectate the full match.")
    : (language === "zh" ? "你选择一个座位加入对局，其余玩家由 AI 扮演。" : "Pick a seat to join. Other players are AI-controlled.");

  const buttonText = isAi
    ? (language === "zh" ? "开始 AI 对局" : "Start AI Match")
    : (language === "zh" ? "开始真人参与对局" : "Start Human Match");

  return (
    <div className="w-full space-y-5 rounded-xl border border-border/40 bg-cardBackground/80 backdrop-blur-sm p-6 shadow-[0_8px_40px_rgba(0,0,0,0.3)]">
      {/* Mode toggle */}
      <div>
        <label className="block text-xs font-medium text-text-sub/60 mb-2.5 uppercase tracking-wider min-h-[1em]">{t("gameMode", language)}</label>
        <div className="flex rounded-lg border border-border/40 p-0.5 bg-border/5">
          {(["ai", "human"] as const).map((m) => (
            <button key={m} data-testid={`mode-${m}-button`} onClick={() => onModeChange(m)}
              className={`flex-1 py-2.5 text-sm font-medium rounded-md transition-all duration-200 ${
                mode === m ? "bg-primary text-white shadow-[0_2px_8px_rgba(183,131,63,0.3)]" : "text-text-sub/60 hover:text-textPrimary"
              }`}>
              {m === "ai" ? t("aiVsAi", language) : t("humanPlay", language)}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-text-sub/50 mt-2 leading-relaxed min-h-[2.25em]">{modeDesc}</p>
      </div>

      {/* Player count */}
      <div>
        <label className="block text-xs font-medium text-text-sub/60 mb-2.5 uppercase tracking-wider">{t("playerCount", language)}</label>
        <div className="flex gap-1.5">
          {[7, 8, 9, 10, 11, 12].map((count) => (
            <button key={count} onClick={() => onPlayerCountChange(count)}
              className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                playerCount === count ? "bg-primary/15 text-primary border border-primary/30 ring-1 ring-primary/20"
                : "text-text-sub/50 border border-transparent hover:text-textPrimary hover:bg-primary/5"
              }`}>
              {count}
            </button>
          ))}
        </div>
      </div>

      {/* Seat selector — human mode only, max-height transition (stable cross-browser) */}
      <div className={`transition-all duration-300 overflow-hidden ${!isAi ? "max-h-60 opacity-100 mt-1" : "max-h-0 opacity-0 mt-0"}`}>
        <label className="block text-xs font-medium text-text-sub/60 mb-2.5 uppercase tracking-wider">{t("yourSeat", language)}</label>
        <div className="grid grid-cols-6 gap-1.5">
          {Array.from({ length: playerCount }, (_, i) => i + 1).map((seat) => (
            <button key={seat} onClick={() => onHumanSeatChange(seat)}
              data-testid={`human-seat-${seat}-button`}
              className={`py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                humanSeat === seat ? "bg-primary/15 text-primary border border-primary/30 ring-1 ring-primary/20"
                : "text-text-sub/50 border border-transparent hover:text-textPrimary hover:bg-primary/5"
              }`}>
              {seat}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && <div className="rounded-lg bg-danger/10 border border-danger/20 px-4 py-2.5 text-sm text-danger text-center">{error}</div>}

      {/* Submit */}
      <Button onClick={onCreateRoom} disabled={isCreating} className="w-full h-12 text-base font-semibold tracking-wide">
        {isCreating ? (
          <span className="flex items-center justify-center gap-2">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            {t("creating", language)}
          </span>
        ) : buttonText}
      </Button>
    </div>
  );
}
