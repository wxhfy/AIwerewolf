"use client";

import { useEffect, useRef } from "react";
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
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => previousFocus?.focus();
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-[3px] sm:p-6"
      onClick={(event) => { if (event.target === event.currentTarget && !isStarting) onClose(); }}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="prepare-modal-title"
        tabIndex={-1}
        className="flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-card border border-border bg-cardBackground shadow-modal animate-scale-in focus:outline-none"
        onKeyDown={(event) => {
          if (event.key === "Escape" && !isStarting) onClose();
          if (event.key !== "Tab") return;
          const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
          const first = buttons?.[0];
          const last = buttons?.[buttons.length - 1];
          if (!first || !last) return;
          if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
            event.preventDefault(); last.focus();
          } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialogRef.current)) {
            event.preventDefault(); first.focus();
          }
        }}
        onClick={(event) => event.stopPropagation()}>
        <div className="shrink-0 border-b border-border px-5 py-5 text-center sm:px-7">
          <h2 id="prepare-modal-title" className="font-display text-xl font-bold text-primary">{t("readyToStart", language)}</h2>
          <p className="mt-1 text-sm text-text-sub">{t("confirmSettingsToStart", language)}</p>
        </div>

        <div className="min-h-0 space-y-5 overflow-y-auto overscroll-contain p-5 timeline-scroll sm:p-7">
          <div className="space-y-1 text-sm">
            {roomInfoRows.map(({ label, value }) => (
              <div key={label} className="flex items-start justify-between gap-4 border-b border-border py-2 last:border-0">
                <span className="shrink-0 text-textSecondary">{label}</span>
                <span className="min-w-0 break-words text-right font-medium text-textPrimary [overflow-wrap:anywhere]">{value}</span>
              </div>
            ))}
          </div>

          <div>
            <p className="text-sm font-medium text-textPrimary mb-2">{t("seatLayout", language)}</p>
            {mode === "ai" && prepareSnapshot?.players ? (
              <div className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2">
                {prepareSnapshot.players.map((player) => (
                  <div key={player.id} className="flex min-w-0 flex-col items-start rounded-button border border-border bg-background/60 p-3 text-xs leading-relaxed">
                    <div className="flex items-center gap-1.5 w-full">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-semibold tabular-nums text-primary">{player.seat}</span>
                      <span className="font-medium text-textPrimary truncate flex-1">{player.name}</span>
                    </div>
                    {player.persona?.mbti && (
                      <span className="mt-2 w-full truncate text-textSecondary">
                        {player.persona.mbti}{player.persona.style_label ? ` · ${player.persona.style_label}` : ""}
                      </span>
                    )}
                    {player.persona?.basic_info && (
                      <span className="mt-1 line-clamp-2 w-full text-textSecondary">
                        {player.persona.basic_info}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-4 gap-2">
                {Array.from({ length: playerCount }, (_, index) => index + 1).map((seat) => (
                  <div
                    key={seat}
                    className={cn(
                      "flex flex-col items-center rounded-button border p-2.5 text-xs",
                      seat === humanSeat && mode === "human" ? "border-primary bg-primary/10" : "border-border bg-background",
                    )}
                  >
                    <span className="font-medium tabular-nums text-textPrimary">{seat}</span>
                    <span className="mt-0.5 text-text-sub">{mode === "human" && seat === humanSeat ? t("you", language) : t("ai", language)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && <p role="alert" className="rounded-button border border-danger/25 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</p>}
        </div>

        <div className="flex shrink-0 gap-3 border-t border-border bg-cardBackground px-5 py-4 sm:px-7">
          <Button variant="secondary" onClick={onClose} disabled={isStarting} className="flex-1">
            {t("cancel", language)}
          </Button>
          <Button onClick={onConfirm} loading={isStarting} className="flex-1">
            {isStarting ? t("starting", language) : t("confirmAndStart", language)}
          </Button>
        </div>
      </div>
    </div>
  );
}
