"use client";

import React from "react";
import { Alignment, Language } from "@/types";
import { t } from "@/lib/i18n";
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
}

function TrophyIcon({ className, size }: { className?: string; size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C7 4 8 7 8 7" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5C17 4 16 7 16 7" />
      <path d="M4 22h16" /><path d="M10 22V8c0-1.1.9-2 2-2s2 .9 2 2v14" /><path d="M8 12h8" />
    </svg>
  );
}

function winReasonText(winner: Alignment, language: Language): string {
  if (winner === Alignment.WOLF) return t("winReasonWolfParity", language);
  return t("winReasonAllWolvesDead", language);
}

export function GameEndPanel({
  winner, day, aliveCount, eventCount, language, showPanel, ballPos, dragRef, onOpen, onClose, onBallMove, onLobby, onReport,
}: GameEndPanelProps) {
  const isVillageWinner = winner === Alignment.VILLAGE;
  const winnerLabel = isVillageWinner ? t("village", language) : t("wolf", language);
  const winTitle = isVillageWinner ? t("villageWins", language) : t("wolvesWin", language);
  const reason = winReasonText(winner, language);
  const winnerColor = isVillageWinner ? "text-success" : "text-danger";

  return (
    <>
      {/* Floating entry — only after modal was dismissed */}
      {!showPanel && (
        <button
          type="button"
          aria-label={t("viewResult", language)}
          onClick={() => { if (!dragRef.current.moved) onOpen(); }}
          onPointerDown={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const ox = ballPos?.x ?? rect.left;
            const oy = ballPos?.y ?? rect.top;
            dragRef.current = { dragging: true, startX: event.clientX, startY: event.clientY, origX: ox, origY: oy, moved: false };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!dragRef.current.dragging) return;
            const dx = event.clientX - dragRef.current.startX;
            const dy = event.clientY - dragRef.current.startY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragRef.current.moved = true;
            if (dragRef.current.moved) {
              onBallMove({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
            }
          }}
          onPointerUp={(event) => { dragRef.current.dragging = false; event.currentTarget.releasePointerCapture(event.pointerId); }}
          onLostPointerCapture={() => { dragRef.current.dragging = false; }}
          className="fixed z-50 right-6 bottom-6 flex items-center gap-3 pl-4 pr-5 py-3 rounded-full animate-scale-in border border-border bg-cardBackground shadow-float hover:shadow-float-hover select-none transition-shadow duration-200 touch-none"
          style={ballPos ? { left: ballPos.x, top: ballPos.y } : undefined}
        >
          <TrophyIcon size={20} className="text-accent animate-breathe" />
          <div className="text-left leading-tight">
            <p className="text-[10px] text-text-sub">{t("resultEntry", language)}</p>
            <p className={`text-sm font-bold ${winnerColor}`}>{winTitle}</p>
            <p className="text-[10px] text-text-sub">{t("viewResult", language)}</p>
          </div>
        </button>
      )}

      {/* Result modal */}
      {showPanel && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/45 backdrop-blur-[3px]" onClick={onClose}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="game-end-title"
            className="text-center animate-scale-in px-6 py-8 rounded-card max-w-sm w-full mx-4 bg-cardBackground shadow-modal-strong"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3">
              <TrophyIcon size={56} className={`mx-auto ${isVillageWinner ? "text-success" : "text-danger"}`} />
            </div>
            <p className="text-sm text-text-sub mb-1">{t("gameOver", language)}</p>
            <h2 id="game-end-title" className={`font-display text-3xl font-bold mb-1 ${winnerColor}`}>
              {winTitle}
            </h2>
            <p className="text-sm text-text-sub mb-5">{reason}</p>

            <div className="grid grid-cols-3 gap-3 mb-5 text-center">
              {[
                [String(day), t("totalDays", language)],
                [String(aliveCount), language === "zh" ? "存活" : "Alive"],
                [`${eventCount} ${language === "zh" ? "条" : ""}`, t("eventsShort", language)],
              ].map(([value, label]) => (
                <div key={label}>
                  <p className="font-display text-2xl font-bold text-primary">{value}</p>
                  <p className="text-xs text-text-sub">{label}</p>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              {onReport && (
                <Button onClick={onReport} className="w-full">
                  {t("viewReview", language)}
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
                className="text-xs text-text-sub underline hover:text-textPrimary transition-colors mt-1"
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
