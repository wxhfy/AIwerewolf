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
  onExport?: () => void;
  reportReady?: boolean;
  reportChecking?: boolean;
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
  winner, day, aliveCount, eventCount, language, showPanel, ballPos, dragRef, onOpen, onClose, onBallMove, onLobby, onReport, onExport,
  reportReady = true,
  reportChecking = false,
}: GameEndPanelProps) {
  const isVillageWinner = winner === Alignment.VILLAGE;
  const winTitle = isVillageWinner ? t("villageWins", language) : t("wolvesWin", language);
  const reason = winReasonText(winner, language);
  const winnerColor = isVillageWinner ? "text-success" : "text-danger";

  return (
    <>
      {/* Floating entry — draggable, only after modal dismissed */}
      {!showPanel && (
        <div
          role="button"
          tabIndex={0}
          aria-label={t("viewResult", language)}
          onClick={() => { if (!dragRef.current.moved) onOpen(); }}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}
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
              onBallMove({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
            }
          }}
          onPointerUp={() => { dragRef.current.dragging = false; }}
          onPointerCancel={() => { dragRef.current.dragging = false; }}
          className="fixed z-50 flex items-center gap-3 pl-4 pr-5 py-3 rounded-full animate-scale-in border border-border bg-cardBackground shadow-float select-none cursor-grab active:cursor-grabbing"
          style={ballPos ? { left: ballPos.x, top: ballPos.y } : { right: 24, bottom: 24 }}
        >
          <TrophyIcon size={20} className="text-accent animate-breathe" />
          <div className="text-left leading-tight">
            <p className="text-[10px] text-text-sub">{t("resultEntry", language)}</p>
            <p className={`text-sm font-bold ${winnerColor}`}>{winTitle}</p>
            <p className="text-[10px] text-text-sub">{t("viewResult", language)}</p>
          </div>
        </div>
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
                <Button onClick={onReport} disabled={!reportReady} className="w-full">
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
