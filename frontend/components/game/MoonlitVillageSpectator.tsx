"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { GameState, Alignment, Role, Player } from "@/types";
import { useSpeechQueue } from "@/hooks/useSpeechQueue";
import { PhaseAnnouncement } from "@/components/game/PhaseAnnouncement";
import { DayNightBlinkTransition } from "@/components/game/DayNightBlinkTransition";
import { seatAvatarSrc } from "@/lib/seatAvatar";
import styles from "./MoonlitVillageSpectator.module.css";

interface MoonlitVillageSpectatorProps {
  roomId: string;
  gameState: GameState | null;
  phase: any;
  controller: any;
}

const roleNames: Record<string, string> = {
  [Role.VILLAGER]: "村民",
  [Role.WEREWOLF]: "狼人",
  [Role.WHITE_WOLF_KING]: "白狼王",
  [Role.SEER]: "预言家",
  [Role.WITCH]: "女巫",
  [Role.HUNTER]: "猎人",
  [Role.GUARD]: "守卫",
  [Role.IDIOT]: "白痴",
  [Role.KNIGHT]: "骑士",
  [Role.ELDER]: "长老",
  [Role.CUPID]: "丘比特",
};

const PHASE_LABEL: Record<string, string> = {
  SETUP: "准备阶段",
  NIGHT_START: "天黑请闭眼",
  NIGHT_GUARD_ACTION: "守卫行动",
  NIGHT_WOLF_ACTION: "狼人行动",
  NIGHT_WITCH_ACTION: "女巫行动",
  NIGHT_SEER_ACTION: "预言家行动",
  NIGHT_RESOLVE: "夜晚结算",
  DAY_START: "天亮了",
  DAY_BADGE_SIGNUP: "警徽竞选报名",
  DAY_BADGE_SPEECH: "警徽竞选发言",
  DAY_BADGE_ELECTION: "警徽投票",
  DAY_PK_SPEECH: "PK 发言",
  DAY_SPEECH: "白天发言",
  DAY_SHERIFF_CLOSING: "警长归票",
  DAY_VOTE: "白天投票",
  DAY_LAST_WORDS: "遗言",
  DAY_RESOLVE: "白天结算",
  HUNTER_SHOOT: "猎人开枪",
  BADGE_TRANSFER: "警徽移交",
  WHITE_WOLF_KING_BOOM: "白狼王自爆",
  GAME_END: "游戏结束",
};

export function MoonlitVillageSpectator({
  roomId,
  gameState,
  phase,
  controller,
}: MoonlitVillageSpectatorProps) {
  const isNight = phase.isVisualNight;
  const currentTheme = isNight ? "night" : "day";
  const currentPhase = gameState?.phase || "SETUP";
  const day = gameState?.day || 1;
  const winner = gameState?.winner;

  // Active speaker ID
  const activeSpeakerId =
    gameState?.current_speaker_id ||
    gameState?.pending_input?.player_id ||
    controller.derived?.activeSpeakerId;

  // Typewriter speech queue
  const {
    displayedSpeeches,
    currentSpeech,
    isTyping,
    skipCurrent,
  } = useSpeechQueue(gameState?.events, {
    onSpeechComplete: controller.onChatComplete,
  });

  const [showHistory, setShowHistory] = useState(false);

  const players: Player[] = useMemo(() => {
    if (gameState?.players && gameState.players.length > 0) {
      return [...gameState.players].sort((a, b) => a.seat - b.seat);
    }
    return controller.placeholder(1, 7);
  }, [gameState?.players, controller]);

  const playerCount = players.length;

  // Extract votes for display
  const votes = useMemo(() => {
    if (gameState?.votes && Object.keys(gameState.votes).length > 0) {
      return gameState.votes;
    }
    const voteHistory = gameState?.vote_history as Record<number, Record<string, string>> | undefined;
    if (voteHistory) {
      const days = Object.keys(voteHistory).map(Number).filter((n) => !isNaN(n));
      if (days.length > 0) {
        const latestDay = Math.max(...days);
        return voteHistory[latestDay] || {};
      }
    }
    return {};
  }, [gameState?.votes, gameState?.vote_history]);

  const voteList = useMemo(() => {
    const list: Array<{ voterSeat: number; targetSeat: number; voterName: string; targetName: string }> = [];
    for (const [voterId, targetId] of Object.entries(votes)) {
      const voter = players.find((p: Player) => p.id === voterId || String(p.seat) === voterId);
      const target = players.find((p: Player) => p.id === targetId || String(p.seat) === targetId);
      if (voter && target) {
        list.push({
          voterSeat: voter.seat,
          targetSeat: target.seat,
          voterName: voter.name,
          targetName: target.name,
        });
      }
    }
    return list;
  }, [votes, players]);

  // Center judge announcement text
  const judgeAnnouncement = useMemo(() => {
    if (winner) {
      return winner === Alignment.WOLF ? "对局结束，狼人阵营获胜！" : "对局结束，好人阵营获胜！";
    }
    if (gameState?.pending_input?.request) {
      return gameState.pending_input.request;
    }
    if (currentPhase.includes("NIGHT")) {
      return "夜深人静，请闭眼入眠...";
    }
    if (currentPhase.includes("VOTE")) {
      return "放逐投票进行中，请村民们做出裁决。";
    }
    if (currentPhase.includes("SPEECH")) {
      const activePlayer = players.find((p) => p.id === activeSpeakerId);
      return activePlayer ? `请 ${activePlayer.seat} 号玩家 ${activePlayer.name} 发言` : "自由发言讨论中...";
    }
    return controller.statusTitle || "等待游戏进程推进...";
  }, [winner, gameState?.pending_input, currentPhase, activeSpeakerId, players, controller.statusTitle]);

  // Seat ellipse geometry for desktop: tokens placed at the rim of the central table
  const seatPositions = useMemo(() => {
    const coords: Record<number, { x: number; y: number }> = {};
    for (let i = 0; i < playerCount; i++) {
      const seat = players[i].seat;
      const angle = -Math.PI / 2 + (2 * Math.PI * i) / playerCount;
      // Ellipse radii in percentages (42% X, 38% Y)
      const x = 50 + 42 * Math.cos(angle);
      const y = 50 + 38 * Math.sin(angle);
      coords[seat] = { x, y };
    }
    return coords;
  }, [playerCount, players]);

  // Active speech for bottom dialogue dock
  const activeSpeech =
    currentSpeech ||
    (displayedSpeeches.length > 0 ? displayedSpeeches[displayedSpeeches.length - 1] : null);

  const speakerPlayer = activeSpeech
    ? players.find((p) => p.id === activeSpeech.actorId || p.seat === activeSpeech.actorSeat)
    : null;
  const speakerName =
    speakerPlayer?.name ||
    activeSpeech?.actorName ||
    (isNight ? "月下村庄" : "村庄广播");
  const speakerSeat =
    speakerPlayer?.seat ??
    (activeSpeech?.actorSeat && activeSpeech.actorSeat > 0 ? activeSpeech.actorSeat : undefined);
  const speakerInitial = speakerPlayer?.name
    ? speakerPlayer.name.slice(0, 1)
    : activeSpeech?.actorName
    ? activeSpeech.actorName.slice(0, 1)
    : isNight
    ? "🌙"
    : "☀️";
  const speechPhaseLabel = activeSpeech
    ? PHASE_LABEL[activeSpeech.phase] || activeSpeech.phase
    : PHASE_LABEL[currentPhase] || "等待中";
  const speechBody = activeSpeech
    ? activeSpeech.displayedText || "..."
    : isNight
    ? "夜幕低垂，村庄寂静。等待玩家发言..."
    : "天亮了，等待玩家开始发言...";

  return (
    <div
      data-theme={currentTheme}
      data-phase={phase.visualPhaseGroup}
      data-phase-aware
      className={`${styles.spectatorRoom} relative flex h-screen [height:100dvh] w-full max-w-full flex-col overflow-hidden`}
    >
      {/* ── DayNight Blink Transition ── */}
      <DayNightBlinkTransition
        blinkPhase={phase.blinkPhase}
        onCloseComplete={phase.onBlinkCloseComplete}
        onPauseComplete={phase.onBlinkPauseComplete}
        onOpenComplete={phase.onBlinkOpenComplete}
      />

      {/* ── Phase Announcement Overlay (hidden on winner) ── */}
      {!winner && phase.phaseAnnouncement && (
        <PhaseAnnouncement
          group={phase.phaseAnnouncement.group}
          visible={phase.phaseAnnouncement.visible}
          text={phase.phaseAnnouncement.text}
        />
      )}

      {/* ── Top Bar / HUD ── */}
      <header className={styles.topHud}>
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-1.5 text-xs text-amber-200/70 transition-colors hover:text-amber-100 font-serif"
          >
            <span>←</span>
            <span className="hidden sm:inline">大厅</span>
          </Link>
          <div className="h-3.5 w-px bg-amber-900/50" />
          <div className="flex items-center gap-2">
            <span className="text-sm select-none" role="img" aria-label="phase-icon">
              {isNight ? "🌙" : "☀️"}
            </span>
            <h1 className="font-display text-xs sm:text-sm font-semibold tracking-wider text-amber-100/90">
              月下村庄 · AI 观战
            </h1>
          </div>
          <span className="hidden rounded border border-amber-900/40 bg-[#120a05]/70 px-2 py-0.5 text-[11px] font-mono text-amber-300/70 sm:inline">
            房间: {roomId.slice(0, 8)}
          </span>
        </div>

        <div className="flex items-center gap-2.5">
          {/* Reconnect Indicator */}
          {controller.isReconnecting && (
            <div
              data-testid="reconnect-indicator"
              role="status"
              className="flex items-center gap-1.5 rounded-full border border-amber-500/50 bg-amber-950/70 px-2.5 py-0.5 text-xs font-medium text-amber-300 animate-pulse"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              <span>网络重连中...</span>
            </div>
          )}

          {/* God view notice */}
          {controller.godViewNotice && (
            <div
              role="alert"
              className="flex items-center gap-1.5 rounded border border-red-700/50 bg-red-950/70 px-2 py-0.5 text-xs text-red-300"
            >
              <span>{controller.godViewNotice}</span>
              <button
                type="button"
                onClick={() => controller.setGodViewNotice(null)}
                className="ml-1 opacity-70 hover:opacity-100"
                aria-label="关闭提示"
              >
                ✕
              </button>
            </div>
          )}

          {/* Pause / Resume Controls */}
          {!winner && (
            <div className="flex items-center gap-1.5">
              {controller.isPaused ? (
                <button
                  type="button"
                  onClick={controller.resumeGame}
                  className="rounded border border-amber-700/60 bg-amber-950/60 hover:bg-amber-900/60 px-2.5 py-0.5 text-xs font-medium text-amber-200 transition-colors"
                >
                  继续
                </button>
              ) : (
                <button
                  type="button"
                  onClick={controller.pauseGame}
                  className="rounded border border-amber-900/50 bg-[#140c06]/80 hover:bg-amber-950/60 px-2.5 py-0.5 text-xs font-medium text-amber-300/70 hover:text-amber-200 transition-colors"
                >
                  暂停
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      {/* ── Main View: Retro Village Table Arena ── */}
      <main className="relative flex flex-1 min-h-0 w-full flex-col overflow-hidden p-2 sm:p-4">
        {/* Mobile Top Seats Strip (<768px): Two rows horizontally scrollable with table token chips */}
        <div className="block md:hidden w-full shrink-0 overflow-x-auto pb-2 scrollbar-none">
          <div className="grid grid-rows-2 grid-flow-col auto-cols-[135px] gap-2 min-w-max px-2">
            {players.map((player) => {
              const isActive = player.id === activeSpeakerId || player.seat === activeSpeakerId;
              const isAlive = player.alive;
              return (
                <div
                  key={player.seat}
                  data-testid={`seat-${player.seat}`}
                  data-alive={isAlive ? "true" : "false"}
                  data-active={isActive ? "true" : "false"}
                  className={`flex items-center gap-2 rounded-lg border p-1.5 text-xs transition-all duration-300 ${
                    isActive
                      ? "border-amber-400 bg-[#2f1b0e] shadow-[0_0_12px_rgba(245,158,11,0.5)]"
                      : isAlive
                      ? "border-amber-950/70 bg-[#1e130a]/90 text-amber-100"
                      : "border-stone-800 bg-stone-950/80 text-stone-400"
                  }`}
                >
                  {/* ~2rem Circular Portrait + Badges */}
                  <div className="relative shrink-0">
                    <div
                      className={`relative h-8 w-8 overflow-hidden rounded-full border shadow-sm ${
                        isActive
                          ? "border-amber-400 ring-2 ring-amber-400/80"
                          : isAlive
                          ? "border-amber-700/60 bg-[#25150b]"
                          : "border-stone-700 bg-stone-950"
                      }`}
                    >
                      <img
                        src={seatAvatarSrc(player.seat)}
                        alt={`${player.name} 的头像`}
                        loading="eager"
                        decoding="async"
                        className={`h-full w-full object-cover object-[center_top] ${
                          !isAlive ? "grayscale contrast-75 brightness-75 opacity-70" : ""
                        }`}
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                        }}
                      />
                    </div>

                    {/* Wax / Brass Seat number badge */}
                    <span className="absolute -bottom-1 -right-1 z-10 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-gradient-to-br from-amber-700 to-amber-900 border border-amber-400/60 text-[9px] font-bold text-amber-100 font-display select-none shadow-sm">
                      {player.seat}
                    </span>

                    {/* Tombstone badge on dead seats */}
                    {!isAlive && (
                      <span
                        className="absolute -top-1 -left-1 z-10 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-stone-900 border border-stone-600 text-[8px] select-none shadow-sm"
                        title="出局"
                        aria-label="出局"
                      >
                        🪦
                      </span>
                    )}
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="truncate font-display font-semibold text-amber-100">{player.name}</p>
                    <p className="truncate text-[10px] text-amber-300/60">
                      {isAlive ? (isActive ? "发言中" : `${player.seat}号位`) : "阵亡"}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Mobile Vote Notice Strip (<768px) */}
        {voteList.length > 0 && (
          <div className="block md:hidden shrink-0 px-2 py-1 mb-1">
            <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-amber-950/70 bg-[#170e07]/90 p-2 text-xs">
              <span className="font-semibold text-amber-300/80 font-serif">投票:</span>
              {voteList.map((item) => (
                <span
                  key={`${item.voterSeat}-${item.targetSeat}`}
                  data-testid="vote-arrow"
                  className="rounded border border-amber-800/40 bg-amber-950/70 px-1.5 py-0.5 font-mono text-[11px] text-amber-300"
                >
                  {item.voterSeat}号 → {item.targetSeat}号
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Desktop Wooden Table Arena (>=768px) */}
        <div className="hidden md:flex relative flex-1 min-h-0 w-full items-center justify-center p-3 lg:p-6">
          <div className={styles.tableOuterWrap}>
            {/* The Real Central Wooden Table (Oval Surface with Carved Rim & Wood Grain) */}
            <div className={styles.tableSurface} />

            {/* SVG Vote Arrows Overlay */}
            <svg className="absolute inset-0 h-full w-full pointer-events-none z-10" viewBox="0 0 100 100">
              <defs>
                <marker
                  id="arrowhead"
                  markerWidth="6"
                  markerHeight="6"
                  refX="5"
                  refY="3"
                  orient="auto"
                >
                  <polygon points="0 0, 6 3, 0 6" fill="#f59e0b" />
                </marker>
              </defs>
              {voteList.map((vote) => {
                const from = seatPositions[vote.voterSeat];
                const to = seatPositions[vote.targetSeat];
                if (!from || !to) return null;
                return (
                  <line
                    key={`${vote.voterSeat}-${vote.targetSeat}`}
                    data-testid="vote-arrow"
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke="#f59e0b"
                    strokeWidth="0.85"
                    strokeDasharray="2.5,1.5"
                    markerEnd="url(#arrowhead)"
                    className="opacity-85"
                  />
                );
              })}
            </svg>

            {/* Center Table Inlaid Plaque: Brass / Carved Wood Disk */}
            <div className={styles.centerPlaque}>
              {/* Brass rivets at four cardinal points */}
              <span className={`${styles.rivet} ${styles.rivetTop}`} />
              <span className={`${styles.rivet} ${styles.rivetBottom}`} />
              <span className={`${styles.rivet} ${styles.rivetLeft}`} />
              <span className={`${styles.rivet} ${styles.rivetRight}`} />

              {/* Phase Banner */}
              <div data-testid="phase-banner" data-phase={currentPhase}>
                <p className="font-display text-[11px] font-semibold tracking-widest text-amber-400/90 uppercase">
                  第 {day} {isNight ? "夜" : "天"}
                </p>
                <h2 className="font-display text-base lg:text-lg font-bold text-amber-100 tracking-wider mt-0.5 drop-shadow">
                  {PHASE_LABEL[currentPhase] || currentPhase}
                </h2>
              </div>

              {/* Short judge announcement line */}
              <div className="mt-2 border-t border-amber-900/40 pt-1.5">
                <p className="line-clamp-2 text-[11px] leading-relaxed text-amber-200/75 font-sans">
                  {judgeAnnouncement}
                </p>
              </div>
            </div>

            {/* Circular Seats Ring on Table Rim */}
            {players.map((player) => {
              const pos = seatPositions[player.seat] || { x: 50, y: 50 };
              const isActive = player.id === activeSpeakerId || player.seat === activeSpeakerId;
              const isAlive = player.alive;

              return (
                <div
                  key={player.seat}
                  data-testid={`seat-${player.seat}`}
                  data-alive={isAlive ? "true" : "false"}
                  data-active={isActive ? "true" : "false"}
                  style={{
                    left: `${pos.x}%`,
                    top: `${pos.y}%`,
                    transform: "translate(-50%, -50%)",
                  }}
                  className={`${styles.seatTokenContainer} ${isActive ? "z-30" : "z-20"}`}
                >
                  {/* Circular Seat Token Medallion */}
                  <div
                    className={`${styles.tokenMedallion} ${
                      isActive
                        ? styles.tokenActive
                        : isAlive
                        ? styles.tokenAlive
                        : styles.tokenDead
                    }`}
                  >
                    {/* Circular Portrait Image */}
                    <div className={styles.tokenAvatarWrap}>
                      <img
                        src={seatAvatarSrc(player.seat)}
                        alt={`${player.name} 的头像`}
                        loading="eager"
                        decoding="async"
                        className={styles.tokenAvatarImg}
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                        }}
                      />
                      <span className={styles.tokenAvatarFallback}>
                        {player.name ? player.name.slice(0, 1) : player.seat}
                      </span>
                    </div>

                    {/* Corner Wax/Brass Seat Number Badge */}
                    <span className={styles.tokenSeatBadge}>
                      {player.seat}
                    </span>

                    {/* Tombstone badge on dead seats */}
                    {!isAlive && (
                      <span
                        className={styles.tokenTombstoneBadge}
                        title="出局"
                        aria-label="出局"
                      >
                        🪦
                      </span>
                    )}
                  </div>

                  {/* Compact Nameplate beneath Token */}
                  <div className={styles.seatNameplate}>
                    <p className="w-full truncate font-display text-xs font-semibold text-amber-100 drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]">
                      {player.name}
                    </p>
                    <p className="text-[10px] font-medium leading-tight text-amber-300/85">
                      {isAlive ? (isActive ? "发言中" : `${player.seat}号`) : "出局"}
                    </p>

                    {/* Revealed role (post-game disclosure) */}
                    {winner && player.role && (
                      <span className="mt-0.5 inline-block rounded bg-amber-950/90 border border-amber-700/60 px-1 py-0.2 text-[9px] font-medium text-amber-300">
                        {roleNames[player.role] || player.role}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </main>

      {/* ── Collapsible History Strip (if toggled) ── */}
      {showHistory && displayedSpeeches.length > 0 && (
        <div className="relative z-20 w-full px-3 sm:px-6">
          <div className="mx-auto max-h-48 w-full max-w-4xl overflow-y-auto rounded-xl border border-amber-900/60 bg-[#160f08]/98 p-3 shadow-2xl backdrop-blur-md timeline-scroll space-y-2">
            <div className="flex items-center justify-between border-b border-amber-900/40 pb-1.5 text-xs text-amber-300/70">
              <span className="font-display font-semibold text-amber-100">
                发言历史记录 ({displayedSpeeches.length})
              </span>
              <button
                type="button"
                onClick={() => setShowHistory(false)}
                className="opacity-70 hover:opacity-100 text-xs px-1 text-amber-200"
                aria-label="关闭历史记录"
              >
                ✕
              </button>
            </div>
            {displayedSpeeches.map((item, idx) => (
              <div key={`${item.id}-${idx}`} className="border-b border-amber-950/50 pb-2 last:border-0 text-xs">
                <div className="flex items-center gap-2 text-[11px] text-amber-400 font-medium">
                  {item.actorSeat > 0 ? (
                    <div className="relative h-6 w-6 sm:h-7 sm:w-7 shrink-0 overflow-hidden rounded-full border border-amber-600/50 bg-[#25150c] shadow-sm">
                      <img
                        src={seatAvatarSrc(item.actorSeat)}
                        alt={`${item.actorName} 的头像`}
                        loading="eager"
                        decoding="async"
                        className="h-full w-full object-cover object-[center_top]"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.display = "none";
                        }}
                      />
                    </div>
                  ) : (
                    <div className="flex h-6 w-6 sm:h-7 sm:w-7 shrink-0 items-center justify-center rounded-full border border-amber-700/40 bg-amber-950/80 text-[11px]">
                      {item.actorName ? item.actorName.slice(0, 1) : "📜"}
                    </div>
                  )}
                  <span className="font-display font-semibold text-amber-200">
                    {item.actorSeat > 0 ? `${item.actorSeat}号 ` : ""}{item.actorName}
                  </span>
                  <span className="text-[10px] text-amber-300/60">({PHASE_LABEL[item.phase] || item.phase})</span>
                  <span className="opacity-60 text-[10px]">第 {item.day} 天</span>
                </div>
                <p className="mt-1 pl-8 sm:pl-9 text-amber-100/90 leading-relaxed whitespace-pre-wrap">{item.fullText}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Bottom Dialogue Dock: Dark Wood Rail Attached to Table Edge ── */}
      <footer
        data-testid="bottom-dialogue-dock"
        data-phase-aware
        className={styles.bottomRail}
      >
        <div className="mx-auto flex w-full max-w-4xl items-center gap-2.5 sm:gap-3.5">
          {/* Avatar & Seat Seal */}
          <div
            className={`${styles.dockAvatarSeal} ${
              isTyping ? styles.dockAvatarActive : ""
            }`}
          >
            {speakerSeat != null && speakerSeat > 0 ? (
              <div className={styles.dockAvatarWrap}>
                <img
                  src={seatAvatarSrc(speakerSeat)}
                  alt={`${speakerName} 的头像`}
                  loading="eager"
                  decoding="async"
                  className={styles.dockAvatarImg}
                  onError={(e) => {
                    (e.currentTarget as HTMLImageElement).style.display = "none";
                  }}
                />
                <span className={styles.dockAvatarFallback}>
                  {speakerInitial}
                </span>
              </div>
            ) : (
              <span className="font-display text-base sm:text-lg font-bold text-amber-200">
                {speakerInitial}
              </span>
            )}
            {speakerSeat != null && (
              <span className="absolute -bottom-1 -right-1 z-10 flex h-4 w-4 sm:h-5 sm:w-5 items-center justify-center rounded-full bg-gradient-to-br from-amber-700 to-amber-900 border border-amber-400/60 text-[9px] sm:text-[10px] font-bold text-amber-100 shadow-sm font-display select-none">
                {speakerSeat}
              </span>
            )}
          </div>

          {/* Recessed Speech Panel (Talk Strip) */}
          <div
            data-testid={activeSpeech ? "speech-item" : undefined}
            data-event-id={activeSpeech?.id}
            className={styles.recessedSpeechBox}
          >
            {/* Header: Name, Phase, Status, Controls */}
            <div className="mb-0.5 sm:mb-1 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <p className="truncate text-xs sm:text-sm font-display font-bold text-amber-100">
                  {speakerSeat != null ? `${speakerSeat}号 ` : ""}{speakerName}
                </p>
                <span className="truncate rounded border border-amber-800/40 bg-amber-950/60 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                  {speechPhaseLabel}
                </span>
              </div>

              <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
                <span className="rounded-full border border-amber-800/30 bg-amber-950/40 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                  {isTyping ? "发言中" : activeSpeech ? "当前发言" : "等待中"}
                </span>

                {displayedSpeeches.length > 1 && (
                  <button
                    type="button"
                    onClick={() => setShowHistory((prev) => !prev)}
                    className="rounded border border-amber-800/40 bg-[#1c120a] hover:bg-[#281a0e] px-2 py-0.5 text-[10px] text-amber-200/80 hover:text-amber-100 transition-colors"
                  >
                    {showHistory ? "收起历史" : `历史 (${displayedSpeeches.length})`}
                  </button>
                )}

                <button
                  type="button"
                  data-testid="skip-typing"
                  onClick={skipCurrent}
                  disabled={!isTyping}
                  className={`rounded border px-2.5 py-0.5 sm:px-3 sm:py-1 text-[11px] sm:text-xs font-medium transition-all ${
                    isTyping
                      ? "border-amber-600/70 bg-gradient-to-b from-amber-700 to-amber-900 text-amber-100 hover:brightness-110 cursor-pointer shadow-sm"
                      : "border-stone-800/60 bg-stone-900/30 text-stone-600 cursor-not-allowed opacity-50"
                  }`}
                >
                  跳过
                </button>
              </div>
            </div>

            {/* Typewriter Speech Text */}
            <div
              data-testid="bottom-dialogue-text-wrap"
              className="max-h-14 sm:max-h-16 overflow-y-auto timeline-scroll text-xs sm:text-sm leading-relaxed text-amber-100/90 font-sans"
            >
              <span data-testid="bottom-dialogue-text" className="whitespace-pre-wrap break-words">
                {speechBody}
              </span>
              {isTyping && (
                <span className="inline-block h-3.5 w-1 bg-amber-400 ml-1 animate-pulse align-middle" />
              )}
            </div>
          </div>
        </div>
      </footer>

      {/* ── Game End Settlement Panel: Wooden Ledger Board ── */}
      {winner && (
        <div
          data-testid="game-end-panel"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md"
        >
          <div className={styles.settlementBoard}>
            {/* Winner Icon */}
            <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full border-2 border-amber-600/60 bg-amber-950/70 text-3xl shadow-[0_0_20px_rgba(245,158,11,0.3)]">
              {winner === Alignment.WOLF ? "🐺" : "🌿"}
            </div>

            <h2 className="font-display text-2xl font-bold text-amber-100 drop-shadow">
              {winner === Alignment.WOLF ? "狼人阵营获胜" : "好人阵营获胜"}
            </h2>

            <p className="mt-1 text-xs text-amber-300/70 font-serif">
              历经 {day} 天对决，胜负已分。公开身份已揭示：
            </p>

            {/* Revealed Roles Ledger Grid */}
            <div className="mt-4 max-h-56 overflow-y-auto rounded-xl border border-amber-900/40 bg-[#120a06]/80 p-3 timeline-scroll">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {players.map((p) => (
                  <div
                    key={p.seat}
                    className={`flex items-center gap-2 rounded-lg border p-2 text-left text-xs transition-colors ${
                      p.alive
                        ? "border-amber-950/80 bg-[#1e130a]/85"
                        : "border-stone-800/80 bg-stone-950/70 opacity-75"
                    }`}
                  >
                    <div className="relative shrink-0">
                      <div
                        className={`relative h-8 w-8 sm:h-9 sm:w-9 overflow-hidden rounded-full border shadow-sm ${
                          p.alive
                            ? "border-amber-600/60 bg-[#25150b]"
                            : "border-stone-700 bg-stone-950"
                        }`}
                      >
                        <img
                          src={seatAvatarSrc(p.seat)}
                          alt={`${p.name} 的头像`}
                          loading="eager"
                          decoding="async"
                          className={`h-full w-full object-cover object-[center_top] ${
                            !p.alive ? "grayscale contrast-75 brightness-75 opacity-70" : ""
                          }`}
                          onError={(e) => {
                            (e.currentTarget as HTMLImageElement).style.display = "none";
                          }}
                        />
                      </div>
                      {/* Seat badge */}
                      <span className="absolute -bottom-1 -right-1 z-10 flex h-3.5 w-3.5 sm:h-4 sm:w-4 items-center justify-center rounded-full bg-gradient-to-br from-amber-700 to-amber-900 border border-amber-400/60 text-[9px] sm:text-[10px] font-bold text-amber-100 font-display select-none shadow-sm">
                        {p.seat}
                      </span>
                      {/* Tombstone badge if dead */}
                      {!p.alive && (
                        <span
                          className="absolute -top-1 -left-1 z-10 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-stone-900 border border-stone-600 text-[8px] select-none shadow-sm"
                          title="出局"
                          aria-label="出局"
                        >
                          🪦
                        </span>
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate font-display font-semibold text-amber-100">{p.name}</p>
                      <p className="truncate text-[10px] text-amber-300/70">
                        {p.role ? roleNames[p.role] || p.role : "未知"}
                        <span className="ml-1 opacity-70">({p.alive ? "存活" : "出局"})</span>
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Action Buttons */}
            <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
              <Link
                href="/"
                className="rounded border border-amber-800/60 bg-[#1e1208] px-4 py-2 text-xs font-semibold text-amber-100 hover:border-amber-600 transition-colors"
              >
                返回大厅
              </Link>
              {gameState?.id && (
                <Link
                  href={`/games/${gameState.id}/report`}
                  className="rounded border border-amber-600 bg-gradient-to-b from-amber-700 to-amber-900 px-4 py-2 text-xs font-semibold text-amber-100 hover:brightness-110 transition-all shadow-sm"
                >
                  查看对局复盘
                </Link>
              )}
              <button
                type="button"
                onClick={controller.exportGameRecord}
                className="rounded border border-amber-900/50 bg-transparent px-4 py-2 text-xs font-medium text-amber-300/70 hover:text-amber-100 transition-colors"
              >
                导出记录
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
