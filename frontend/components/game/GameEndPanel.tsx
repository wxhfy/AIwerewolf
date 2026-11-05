"use client";

import React, { useEffect, useRef } from "react";
import { Alignment, Language, type Player } from "@/types";
import { t, tRole } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

interface GameEndPanelProps {
  winner: Alignment;
  day: number;
  aliveCount: number;
  eventCount: number;
  language: Language;
  showPanel: boolean;
  ballPos: { x: number; y: number } | null;
  dragRef: React.MutableRefObject<{ dragging: boolean; startX: number; startY: number; origX: number; origY: number; moved: boolean }>;
  onOpen: () => void;
  onClose: () => void;
  onBallMove: (position: { x: number; y: number }) => void;
  onLobby: () => void;
  onReport?: () => void;
  onExport?: () => void;
  reportReady?: boolean;
  reportChecking?: boolean;
  players?: Player[];
}

function TrophyIcon({ className, size }: { className?: string; size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M8 3h8v5a4 4 0 0 1-8 0V3Z" /><path d="M8 5H5v2a4 4 0 0 0 4 4M16 5h3v2a4 4 0 0 1-4 4M12 12v5M8 21v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2H8Z" />
    </svg>
  );
}

function winReasonText(winner: Alignment, language: Language): string {
  if (winner === Alignment.WOLF) return t("winReasonWolfParity", language);
  return t("winReasonAllWolvesDead", language);
}

export function GameEndPanel({
  winner, day, aliveCount, eventCount, language, showPanel, ballPos, dragRef, onOpen, onClose, onBallMove, onLobby, onReport, onExport,
  reportReady = true,
  reportChecking = false,
  players = [],
}: GameEndPanelProps) {
  const isVillageWinner = winner === Alignment.VILLAGE;
  const winTitle = isVillageWinner ? t("villageWins", language) : t("wolvesWin", language);
  const reason = winReasonText(winner, language);
  const winnerColor = isVillageWinner ? "text-success" : "text-danger";
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showPanel) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus({ preventScroll: true });
    return () => {
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    };
  }, [showPanel]);

  return (
    <>
      {/* Floating entry — draggable, only after modal dismissed */}
      {!showPanel && (
        <div
          role="button"
          tabIndex={0}
          aria-label={t("viewResult", language)}
          onClick={() => { if (!dragRef.current.moved) onOpen(); }}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }}
          onPointerDown={(event) => {
            event.preventDefault();
            const el = event.currentTarget;
            el.setPointerCapture(event.pointerId);
            const rect = el.getBoundingClientRect();
            dragRef.current = {
              dragging: true, moved: false,
              startX: event.clientX, startY: event.clientY,
              origX: ballPos?.x ?? rect.left, origY: ballPos?.y ?? rect.top,
            };
          }}
          onPointerMove={(event) => {
            if (!dragRef.current.dragging) return;
            const dx = event.clientX - dragRef.current.startX;
            const dy = event.clientY - dragRef.current.startY;
            if (Math.abs(dx) > 2 || Math.abs(dy) > 2) dragRef.current.moved = true;
            if (dragRef.current.moved) {
              const rect = event.currentTarget.getBoundingClientRect();
              onBallMove({
                x: Math.max(12, Math.min(window.innerWidth - rect.width - 12, dragRef.current.origX + dx)),
                y: Math.max(12, Math.min(window.innerHeight - rect.height - 12, dragRef.current.origY + dy)),
              });
            }
          }}
          onPointerUp={() => { dragRef.current.dragging = false; }}
          onPointerCancel={() => { dragRef.current.dragging = false; }}
          className="fixed z-50 flex touch-none items-center gap-3 rounded-full border border-accent/30 bg-cardBackground py-2.5 pl-4 pr-5 shadow-float animate-scale-in select-none cursor-grab active:cursor-grabbing"
          style={ballPos ? { left: ballPos.x, top: ballPos.y } : { right: 16, bottom: "max(16px, env(safe-area-inset-bottom))" }}
        >
          <TrophyIcon size={22} className="text-accent" />
          <div className="text-left leading-tight">
            <p className="text-[10px] text-text-sub">{t("resultEntry", language)}</p>
            <p className={`text-sm font-bold ${winnerColor}`}>{winTitle}</p>
          </div>
        </div>
      )}

      {/* Result modal */}
      {showPanel && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/65 p-3 backdrop-blur-sm sm:p-6" onClick={onClose}>
          <div
            ref={dialogRef}
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby="game-end-title"
            aria-describedby="game-end-reason"
            className="relative max-h-[90dvh] w-full max-w-lg overflow-y-auto rounded-card border border-accent/25 bg-cardBackground p-5 text-center shadow-modal-strong outline-none animate-scale-in sm:p-7"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Escape") { event.stopPropagation(); onClose(); }
              if (event.key !== "Tab") return;
              const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
              const first = buttons[0];
              const last = buttons[buttons.length - 1];
              if (!first || !last) return;
              if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
                event.preventDefault(); last.focus();
              } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first.focus();
              }
            }}
          >
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full border border-accent/30 bg-accent/10 text-accent">
              <TrophyIcon size={34} />
            </div>
            <p className="mb-2 text-xs tracking-[0.18em] text-text-sub">{t("gameOver", language)}</p>
            <h2 id="game-end-title" className={`mb-2 font-display text-2xl font-bold sm:text-3xl ${winnerColor}`}>
              {winTitle}
            </h2>
            <p id="game-end-reason" className="mb-5 text-sm leading-relaxed text-text-sub">{reason}</p>

            <div className="mb-5 grid grid-cols-3 divide-x divide-border rounded-button border border-border bg-background py-3 text-center">
              {[
                [String(day), t("totalDays", language)],
                [String(aliveCount), language === "zh" ? "存活" : "Alive"],
                [String(eventCount), t("eventsShort", language)],
              ].map(([value, label]) => (
                <div key={label}>
                  <p className="font-display text-xl font-semibold tabular-nums text-textPrimary">{value}</p>
                  <p className="text-xs text-text-sub">{label}</p>
                </div>
              ))}
            </div>

            {players.length > 0 && (
              <section className="mb-5 text-left" aria-labelledby="game-end-roles">
                <div className="mb-2.5 flex items-center justify-between gap-2">
                  <h3 id="game-end-roles" className="text-sm font-semibold text-textPrimary">{language === "zh" ? "身份揭晓" : "Role reveal"}</h3>
                  <span className="text-xs text-text-sub">{language === "zh" ? `${players.length} 位玩家` : `${players.length} players`}</span>
                </div>
                <div className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2">
                  {[...players].sort((a, b) => a.seat - b.seat).map((player) => (
                    <div key={player.id} className="flex min-w-0 items-center gap-2 rounded-button border border-border bg-background px-2.5 py-2">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold tabular-nums text-primary">{player.seat}</span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-xs font-medium text-textPrimary" title={player.name}>{player.name}</p>
                        <p className={`text-[11px] ${player.alignment === Alignment.WOLF ? "text-danger" : player.alignment === Alignment.VILLAGE ? "text-success" : "text-text-sub"}`}>
                          {player.role ? tRole(player.role, language) : language === "zh" ? "身份未揭示" : "Not revealed"}
                        </p>
                      </div>
                      <span className="shrink-0 text-[10px] text-text-sub">{player.alive ? language === "zh" ? "存活" : "Alive" : language === "zh" ? "出局" : "Out"}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <div className="flex flex-col gap-2">
              {onReport && (
                <Button onClick={onReport} disabled={!reportReady || reportChecking} loading={!reportReady || reportChecking} className="w-full">
                  {!reportReady || reportChecking
                    ? language === "zh" ? "复盘生成中..." : "Generating Review..."
                    : t("viewReview", language)}
                </Button>
              )}
              {onExport && (
                <Button variant="secondary" onClick={onExport} className="w-full">
                  {t("exportGameRecord", language)}
                </Button>
              )}
              <div className="flex gap-2">
                <Button variant="secondary" onClick={onLobby} className="flex-1">
                  {language === "zh" ? "再来一局" : "Play Again"}
                </Button>
                <Button variant="ghost" onClick={onLobby} className="flex-1">
                  {t("backToLobby", language)}
                </Button>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="mt-1 min-h-9 rounded-button text-xs text-text-sub underline decoration-border underline-offset-4 transition-colors duration-200 hover:text-textPrimary"
              >
                {t("closePanel", language)}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
