"use client";

import React from "react";
import { Language } from "@/types";
import { t } from "@/lib/i18n";
import { Button } from "@/components/ui/Button";

interface LobbyConfigCardProps {
  language: Language;
  playerCount: number;
  mode: "ai" | "human";
  humanSeat: number;
  isCreating: boolean;
  error: string;
  onPlayerCountChange: (value: number) => void;
  onModeChange: (mode: "ai" | "human") => void;
  onHumanSeatChange: (seat: number) => void;
  onCreateRoom: () => void;
  onOpenSettings?: () => void;
}

export function LobbyConfigCard(props: LobbyConfigCardProps) {
  const {
    language,
    playerCount,
    mode,
    humanSeat,
    isCreating,
    error,
    onPlayerCountChange,
    onModeChange,
    onHumanSeatChange,
    onCreateRoom,
    onOpenSettings,
  } = props;

  const isAi = mode === "ai";
  const primaryButtonText = isAi
    ? (language === "zh" ? "开一局 AI 观战" : "Start AI Spectate")
    : (language === "zh" ? "创建真人参与对局" : "Create Human Match");

  const modeDesc = isAi
    ? (language === "zh"
        ? "7 位性格迥异的酒馆旅人齐聚圆桌，各自推理、辩驳与决断。以全局视角观赏完整暗涌。"
        : "7 tavern guests gather around the table. Watch their deductions, debates, and votes from a global view.")
    : (language === "zh"
        ? "选择一个席位亲自入局，其余座位由 AI 旅人扮演。"
        : "Pick a seat to join the tavern table. Other guests are AI-controlled.");

  return (
    <div
      className="w-full overflow-hidden rounded-2xl border-2 border-amber-700/60 bg-gradient-to-b from-[#24170d] via-[#1a1009] to-[#120a06] shadow-[0_20px_50px_rgba(0,0,0,0.85)]"
      aria-busy={isCreating}
    >
      {/* Tavern Board Header: Brass Plate & Lamp Ambiance */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-amber-900/60 bg-[#160d07]/90 px-5 py-4 sm:px-7 sm:py-5">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-amber-500/50 bg-amber-950/80 text-xl shadow-[0_0_12px_rgba(245,158,11,0.25)]">
            🕯️
          </span>
          <div>
            <h2 className="font-display text-lg sm:text-xl font-bold tracking-wide text-amber-100 drop-shadow">
              {language === "zh" ? "月下酒馆 · 圆桌对局" : "Moonlit Tavern · Match Setup"}
            </h2>
            <p className="mt-0.5 text-xs text-amber-300/70 font-serif">
              {language === "zh" ? "推门围炉入座，静待钟声敲响。" : "Gather round the hearth as the bells toll."}
            </p>
          </div>
        </div>
        <span className="rounded-full border border-amber-600/50 bg-amber-950/80 px-3 py-1 text-xs font-semibold tabular-nums text-amber-300 shadow-inner">
          {playerCount} {language === "zh" ? "人圆桌" : "Players"}
        </span>
      </div>

      <div className="space-y-6 p-5 sm:p-7">
        {/* Mode Selector */}
        <fieldset disabled={isCreating} aria-describedby="lobby-mode-description">
          <legend className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-amber-300/80">
            {language === "zh" ? "对局模式" : t("gameMode", language)}
          </legend>
          <div className="grid grid-cols-2 gap-2 rounded-xl border border-amber-950/80 bg-[#130b06]/90 p-1.5 shadow-inner">
            <button
              type="button"
              data-testid="mode-ai-button"
              onClick={() => onModeChange("ai")}
              aria-pressed={isAi}
              className={`min-h-11 rounded-lg border text-sm font-semibold transition-all duration-200 ${
                isAi
                  ? "border-amber-500/70 bg-gradient-to-b from-amber-700/80 to-amber-900/80 text-amber-100 shadow-[0_2px_8px_rgba(0,0,0,0.5)]"
                  : "border-transparent text-amber-200/60 hover:text-amber-100 hover:bg-amber-950/40"
              }`}
            >
              {language === "zh" ? "AI 观战（推荐）" : t("aiVsAi", language)}
            </button>
            <button
              type="button"
              data-testid="mode-human-button"
              onClick={() => onModeChange("human")}
              aria-pressed={!isAi}
              className={`min-h-11 rounded-lg border text-sm font-semibold transition-all duration-200 ${
                !isAi
                  ? "border-amber-500/70 bg-gradient-to-b from-amber-700/80 to-amber-900/80 text-amber-100 shadow-[0_2px_8px_rgba(0,0,0,0.5)]"
                  : "border-transparent text-amber-200/60 hover:text-amber-100 hover:bg-amber-950/40"
              }`}
            >
              {language === "zh" ? "真人入局" : t("humanPlay", language)}
            </button>
          </div>
          <p id="lobby-mode-description" className="mt-2.5 text-xs leading-relaxed text-amber-200/70">
            {modeDesc}
          </p>
        </fieldset>

        {/* Player Count Selection (default 7) */}
        <fieldset disabled={isCreating}>
          <div className="mb-2.5 flex items-center justify-between">
            <legend className="text-xs font-semibold uppercase tracking-wider text-amber-300/80">
              {language === "zh" ? "圆桌人数" : t("playerCount", language)}
            </legend>
            <span className="text-[11px] text-amber-400/80 font-serif">
              {playerCount === 7 ? (language === "zh" ? "标准 7 人局（推荐）" : "Standard 7-seat match") : ""}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {[7, 8, 9, 10, 11, 12].map((count) => {
              const isSelected = playerCount === count;
              return (
                <button
                  key={count}
                  type="button"
                  onClick={() => onPlayerCountChange(count)}
                  aria-pressed={isSelected}
                  aria-label={language === "zh" ? `${count} 人局` : `${count} players`}
                  className={`min-h-11 rounded-lg border text-sm font-bold tabular-nums transition-all duration-200 ${
                    isSelected
                      ? "border-amber-500 bg-amber-600/30 text-amber-200 ring-1 ring-amber-400/50 shadow-[0_0_10px_rgba(245,158,11,0.25)]"
                      : "border-amber-900/40 bg-[#160d07]/70 text-amber-300/60 hover:border-amber-700/60 hover:text-amber-200"
                  }`}
                >
                  {count} {language === "zh" ? "人" : ""}
                </button>
              );
            })}
          </div>
        </fieldset>

        {/* Human Seat Selection (Secondary hook only when human mode is selected) */}
        {!isAi && (
          <fieldset disabled={isCreating} className="border-t border-amber-900/50 pt-5 animate-scale-in">
            <legend className="sr-only">{t("yourSeat", language)}</legend>
            <div className="mb-2.5 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-amber-300/80">
              <span>{t("yourSeat", language)}</span>
              <span className="text-amber-400 font-bold">{humanSeat} {language === "zh" ? "号位" : "seat"}</span>
            </div>
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
              {Array.from({ length: playerCount }, (_, i) => i + 1).map((seat) => (
                <button
                  key={seat}
                  type="button"
                  onClick={() => onHumanSeatChange(seat)}
                  data-testid={`human-seat-${seat}-button`}
                  aria-pressed={humanSeat === seat}
                  aria-label={language === "zh" ? `${seat} 号位` : `Seat ${seat}`}
                  className={`min-h-10 rounded-lg border text-xs font-bold tabular-nums transition-all ${
                    humanSeat === seat
                      ? "border-amber-500 bg-amber-600/30 text-amber-200 ring-1 ring-amber-400/50 shadow-sm"
                      : "border-amber-900/40 bg-[#160d07]/70 text-amber-300/60 hover:border-amber-700/60 hover:text-amber-200"
                  }`}
                >
                  {seat} 号
                </button>
              ))}
            </div>
          </fieldset>
        )}

        {/* Collapsed Dev / Advanced settings disclosure (clean & out of the way) */}
        {onOpenSettings && (
          <div className="border-t border-amber-950/70 pt-2">
            <button
              type="button"
              onClick={onOpenSettings}
              className="text-xs text-amber-300/60 hover:text-amber-200 transition-colors flex items-center gap-1.5 py-1"
            >
              <span>⚙️</span>
              <span>{language === "zh" ? "进阶 / 开发设置" : "Advanced / Dev Settings"}</span>
            </button>
          </div>
        )}

        {error && (
          <div role="alert" className="rounded-xl border border-red-700/60 bg-red-950/80 px-4 py-3 text-xs leading-relaxed text-red-200 shadow-md">
            {error}
          </div>
        )}

        {/* Big Primary CTA */}
        <div className="space-y-3 border-t border-amber-900/60 pt-5">
          <Button
            onClick={onCreateRoom}
            loading={isCreating}
            size="lg"
            className="w-full min-h-14 rounded-xl border border-amber-400/80 bg-gradient-to-b from-amber-500 via-amber-600 to-amber-700 text-base sm:text-lg font-bold text-amber-50 shadow-[0_0_25px_rgba(245,158,11,0.45)] hover:brightness-110 active:scale-[0.99] transition-all"
          >
            {isCreating ? t("creating", language) : primaryButtonText}
          </Button>
          <p role="status" className="text-center text-xs leading-relaxed text-amber-300/70 font-serif">
            {isCreating
              ? (language === "zh" ? "酒馆掌柜正在安排座位，请稍候…" : "Arranging table and seats...")
              : (language === "zh" ? "点击开局，推门入席观摩 7 位旅人的暗夜较量" : "Take your seat and watch the story unfold.")}
          </p>
        </div>
      </div>
    </div>
  );
}
