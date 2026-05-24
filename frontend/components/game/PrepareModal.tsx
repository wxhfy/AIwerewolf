"use client";

import { Language, PrepareSnapshot, RoomInfoRow } from "@/types";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";

interface PrepareModalProps {
  language: Language;
  roomInfoRows: RoomInfoRow[];
  mode: "ai" | "human";
  prepareSnapshot: PrepareSnapshot | null;
  playerCount: number;
  humanSeat: number;
  error: string;
  isStarting: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function PrepareModal({
  language,
  roomInfoRows,
  mode,
  prepareSnapshot,
  playerCount,
  humanSeat,
  error,
  isStarting,
  onClose,
  onConfirm,
}: PrepareModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/45 backdrop-blur-[2px]"
      onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="prepare-modal-title"
        className="w-full max-w-sm space-y-5 rounded-card border border-border bg-cardBackground p-6 shadow-modal animate-scale-in"
        onClick={(event) => event.stopPropagation()}>
        <div className="text-center">
          <h2 id="prepare-modal-title" className="font-display text-xl font-bold text-primary">{t("readyToStart", language)}</h2>
          <p className="mt-1 text-sm text-text-sub">{t("confirmSettingsToStart", language)}</p>
        </div>

        <div className="space-y-2 text-sm">
          {roomInfoRows.map(({ label, value }) => (
            <div key={label} className="flex justify-between border-b border-border py-1.5">
              <span className="text-text-sub">{label}</span>
              <span className="font-medium text-textPrimary">{value}</span>
            </div>
          ))}
        </div>

        <div>
          <p className="text-sm font-medium text-textPrimary mb-2">{t("seatLayout", language)}</p>
          {mode === "ai" && prepareSnapshot?.players ? (
            <div className="grid grid-cols-2 gap-1.5">
              {prepareSnapshot.players.map((player) => (
                <div key={player.id} className="flex flex-col items-start rounded-lg border border-border bg-background p-2 text-xs leading-tight">
                  <div className="flex items-center gap-1.5 w-full">
                    <span className="font-bold text-textPrimary">{player.seat}</span>
                    <span className="font-medium text-textPrimary truncate flex-1">{player.name}</span>
                  </div>
                  {player.persona?.mbti && (
                    <span className="text-text-sub/80 text-[10px] mt-0.5 truncate w-full">
                      {player.persona.mbti}{player.persona.style_label ? ` · ${player.persona.style_label}` : ""}
                    </span>
                  )}
                  {player.persona?.basic_info && (
                    <span className="text-text-sub/60 text-[10px] mt-0.5 line-clamp-2 w-full">
                      {player.persona.basic_info}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-1.5">
              {Array.from({ length: playerCount }, (_, index) => index + 1).map((seat) => (
                <div
                  key={seat}
                  className={cn(
                    "flex flex-col items-center rounded-lg border p-2 text-xs",
                    seat === humanSeat && mode === "human" ? "border-primary bg-primary/10" : "border-border bg-background",
                  )}
                >
                  <span className="font-medium text-textPrimary">{seat}</span>
                  <span className="mt-0.5 text-text-sub">{mode === "human" && seat === humanSeat ? t("you", language) : t("ai", language)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {error && <p className="text-sm text-danger text-center">{error}</p>}

        <div className="flex gap-3 pt-1">
          <Button variant="ghost" onClick={onClose} className="flex-1">
            {t("cancel", language)}
          </Button>
          <Button onClick={onConfirm} disabled={isStarting} className="flex-1">
            {isStarting ? t("starting", language) : t("confirmAndStart", language)}
          </Button>
        </div>
      </div>
    </div>
  );
}
