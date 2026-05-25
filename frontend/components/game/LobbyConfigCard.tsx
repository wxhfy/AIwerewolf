"use client";

import { Language } from "@/types";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

interface LobbyConfigCardProps {
  language: Language;
  playerCount: number;
  mode: "ai" | "human";
  humanSeat: number;
  seed: number;
  isCreating: boolean;
  error: string;
  onPlayerCountChange: (value: number) => void;
  onModeChange: (mode: "ai" | "human") => void;
  onHumanSeatChange: (seat: number) => void;
  onSeedChange: (seed: number) => void;
  onCreateRoom: () => void;
}

export function LobbyConfigCard({
  language,
  playerCount,
  mode,
  humanSeat,
  seed,
  isCreating,
  error,
  onPlayerCountChange,
  onModeChange,
  onHumanSeatChange,
  onSeedChange,
  onCreateRoom,
}: LobbyConfigCardProps) {
  return (
    <div className="w-full max-w-md space-y-5 rounded-card border border-border bg-cardBackground p-6 shadow-card">
      <div>
        <label className="block text-sm font-medium text-textPrimary mb-2">{t("gameMode", language)}</label>
        <div className="flex overflow-hidden rounded-button border border-border">
          {(["ai", "human"] as const).map((nextMode) => (
            <button key={nextMode} onClick={() => onModeChange(nextMode)}
              className={`flex-1 py-2 text-sm font-medium ${mode === nextMode ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>
              {nextMode === "ai" ? t("aiVsAi", language) : t("humanPlay", language)}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-textPrimary mb-2">{t("playerCount", language)}</label>
        <select value={playerCount} onChange={(event) => onPlayerCountChange(Number(event.target.value))}
          className="h-10 w-full rounded-button border border-border bg-background px-3 text-sm text-textPrimary">
          {[7, 8, 9, 10, 11, 12].map((count) => <option key={count} value={count}>{count} {t("playersUnit", language)}</option>)}
        </select>
      </div>

      {mode === "human" && (
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">{t("yourSeat", language)}</label>
          <select value={humanSeat} onChange={(event) => onHumanSeatChange(Number(event.target.value))}
            className="h-10 w-full rounded-button border border-border bg-background px-3 text-sm text-textPrimary">
            {Array.from({ length: playerCount }, (_, index) => index + 1).map((seat) => <option key={seat} value={seat}>{t("seat", language)} {seat}</option>)}
          </select>
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-textPrimary mb-2">{t("seed", language)}</label>
        <input type="number" value={seed} onChange={(event) => onSeedChange(Number(event.target.value) || 0)}
          className="h-10 w-full rounded-button border border-border bg-background px-3 text-sm text-textPrimary" />
      </div>

      {error && <p className="text-sm text-danger text-center">{error}</p>}

      <Button onClick={onCreateRoom} disabled={isCreating} className="w-full h-11 text-base">
        {isCreating ? t("creating", language) : t("startGame", language)}
      </Button>
    </div>
  );
}
