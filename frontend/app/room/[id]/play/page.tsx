"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import {
  WebSocketMessage,
  WebSocketRequest,
  Language,
  ViewMode,
  Phase,
} from "@/types";
import { Button } from "@/components/ui/Button";
import { PlayerCard } from "@/components/game/PlayerCard";
import { ActionPanel } from "@/components/game/ActionPanel";
import { ChatBubble } from "@/components/game/ChatBubble";
import { EventItem } from "@/components/game/EventItem";
import { EventType } from "@/types";
import { PhaseAnnouncement } from "@/components/game/PhaseAnnouncement";
import { apiUrl, wsUrl } from "@/lib/api";

export default function GamePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const roomId = params.id;
  const mode = searchParams.get("mode") || "ai";
  const humanSeat = Number(searchParams.get("human_seat") || 1);

  const {
    language, setLanguage, viewMode, setViewMode, agentType,
    room, setRoom, gameState, setGameState, isPlaying, setIsPlaying,
    speed, seed,
  } = useAppContext();

  const [showWinnerPanel, setShowWinnerPanel] = useState(false);
  const [ballPos, setBallPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, origX: 0, origY: 0, moved: false });
  // Phase announcement state
  const [announcePhase, setAnnouncePhase] = useState<{phase: string; prev: string} | null>(null);
  const lastPhaseRef = useRef("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const [statusTitle, setStatusTitle] = useState(
    gameState?.winner ? t("statusLoaded", language) : t("statusReady", language)
  );
  const wsRef = useRef<WebSocket | null>(null);

  // Auto-scroll to latest messages, pause when user scrolls up
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !autoScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [gameState?.events?.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    autoScrollRef.current = atBottom;
  };

  // Auto-start human mode when no gameState (direct URL access or refresh)
  useEffect(() => {
    if (mode === "human" && !gameState && !isPlaying) {
      startHumanGame();
    }
  }, [mode, roomId]);

  // Sync status when gameState arrives (e.g., from lobby pre-start)
  useEffect(() => {
    if (gameState) {
      if (gameState.winner) {
        setStatusTitle(t("statusLoaded", language));
        setIsPlaying(false);
      } else if (gameState.pending_input) {
        setStatusTitle(t("statusStreaming", language));
        setIsPlaying(true);
      }
    }
  }, [gameState?.id]);

  const isNight = useMemo(() => {
    const p = gameState?.phase || "";
    return p.startsWith("NIGHT") || p === Phase.NIGHT_START || p === Phase.NIGHT_RESOLVE;
  }, [gameState?.phase]);

  useEffect(() => {
    document.documentElement.setAttribute("data-phase", isNight ? "night" : "day");
  }, [isNight]);

  useEffect(() => {
    if (!room || room.id !== roomId) {
      fetch(apiUrl(`/api/rooms/${roomId}`))
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (d) setRoom(d); }).catch(() => {});
    }
  }, [roomId]);

  useEffect(() => {
    if (mode !== "human") {
      setViewMode(ViewMode.MODERATOR);
    }
  }, [mode, setViewMode]);

  // Auto-start the game on first entry in AI mode.
  //
  // The lobby calls /api/rooms/{id}/prepare before navigating here, so
  // gameState already has all players + roles + personas populated when we
  // mount — we can't use "gameState empty" as the trigger anymore (it never
  // is). We instead rely on three signals:
  //   - mode === "ai"
  //   - the game hasn't already ended (winner set)
  //   - we haven't already opened a WebSocket for this room
  //
  // We DON'T mark `autoStartedRef = true` until the setTimeout actually fires,
  // because React 18 Strict Mode (dev) double-mounts: the first mount sets the
  // ref and schedules the timer, the cleanup clears the timer, then the
  // second mount sees ref=true and bails — so nothing ever starts. By only
  // setting the ref inside the timer callback, the cleanup cancels the
  // first attempt cleanly and the second mount re-schedules.
  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (autoStartedRef.current) return;
    if (mode !== "ai") return;
    if (gameState?.winner) return;
    if (isPlaying) return;
    if (wsRef.current) return;
    // Small delay so the WS handler is attached and AppContext is settled.
    const id = setTimeout(() => {
      autoStartedRef.current = true;
      runGame();
    }, 200);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, roomId]);

  function runGame() {
    if (mode === "human") { startHumanGame(); return; }
    if (wsRef.current) wsRef.current.close();
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    // Don't wipe gameState if /prepare already populated the roster — it
    // would flash empty placeholders for the 100-300ms before the WS replays
    // baseline frames. Only clear when this is a fresh "run again" click.
    if (gameState?.winner) setGameState(null);
    const ws = new WebSocket(wsUrl(`/ws/rooms/${roomId}`));
    wsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({
      action: "start", seed, agent_type: agentType,
      show_private: true, delay_ms: speed,  // Always request full data; frontend filters by viewMode
    } as WebSocketRequest));
    ws.onmessage = (e) => {
      const msg: WebSocketMessage = JSON.parse(e.data);
      if (msg.type === "room" && msg.room) setRoom(msg.room);
      if (msg.type === "snapshot" && msg.state) {
        setGameState(msg.state);
        // Detect phase changes for announcement
        const newPhase = msg.state.phase;
        if (newPhase && newPhase !== lastPhaseRef.current) {
          setAnnouncePhase({ phase: newPhase, prev: lastPhaseRef.current });
          lastPhaseRef.current = newPhase;
        }
      }
      if (msg.type === "complete") {
        if (msg.state) setGameState(msg.state);
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false); setStatusTitle(t("statusLoaded", language));
      }
      if (msg.type === "error") { setIsPlaying(false); setStatusTitle(t("statusError", language)); }
    };
    ws.onerror = () => setIsPlaying(false);
    ws.onclose = (ev) => {
      setIsPlaying(false);
      // Auto-reconnect when the socket dies mid-game (network blip, server
      // hiccup, browser pausing tabs). The backend keeps the game running and
      // buffers snapshots, so the reconnect picks up where we left off.
      // We skip reconnect when: (a) the game already finished, (b) we hold
      // the most recent gameState that includes a winner, or (c) we
      // intentionally closed the socket because the user navigated away.
      const finished = gameState?.winner != null;
      const cleanClose = ev.code === 1000 || ev.code === 1001;
      if (!finished && !cleanClose && wsRef.current === ws) {
        setStatusTitle(language === "zh" ? "连接断开，自动重连..." : "Reconnecting…");
        setTimeout(() => {
          if (wsRef.current === ws) runGame();
        }, 800);
      }
    };
  }

  async function startHumanGame() {
    setIsPlaying(true); setStatusTitle(t("statusStreaming", language)); setGameState(null);
    try {
      const res = await fetch(apiUrl(`/api/rooms/${roomId}/start?show_private=true`), { method: "POST" });
      if (!res.ok) throw new Error("Start failed");
      const snap = await res.json();
      setGameState(snap);
      if (snap.winner) { setIsPlaying(false); setStatusTitle(t("statusLoaded", language)); }
    } catch { setIsPlaying(false); setStatusTitle(t("statusError", language)); }
  }

  async function handleHumanAction(data: { target_id?: string | null; speech?: string | null; save?: boolean }) {
    try {
      const res = await fetch(apiUrl(`/api/rooms/${roomId}/action`), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_id: data.target_id || null, speech: data.speech || null, save: data.save || false, reasoning: "Human action from UI" }),
      });
      if (!res.ok) throw new Error("Action failed");
      const snap = await res.json();
      setGameState(snap);
      if (snap.winner) { setIsPlaying(false); setStatusTitle(t("statusLoaded", language)); }
    } catch (err) { console.error("Action error:", err); }
  }

  const dayBlocks = useMemo(() => {
    if (!gameState?.events) return {};
    const b: Record<number, typeof gameState.events> = {};
    for (const ev of gameState.events) { const d = ev.day || 0; if (!b[d]) b[d] = []; b[d].push(ev); }
    return b;
  }, [gameState?.events]);

  // Split players evenly: ceil(N/2) left, floor(N/2) right
  const splitPoint = useMemo(() => Math.ceil((gameState?.players?.length || 7) / 2), [gameState?.players?.length]);
  const leftPlayers = useMemo(() => (gameState?.players || []).filter((p: any) => p.seat <= splitPoint), [gameState?.players, splitPoint]);
  const rightPlayers = useMemo(() => (gameState?.players || []).filter((p: any) => p.seat > splitPoint), [gameState?.players, splitPoint]);
  const aliveCount = gameState?.alive_count ?? (gameState?.players?.filter((p: any) => p.alive).length ?? 0);
  const pendingInput = gameState?.pending_input;
  // Highlight whoever is currently taking a turn — pendingInput covers human
  // turns (waiting for input), current_speaker_id covers AI turns being
  // generated. The PlayerCard uses this flag to glow.
  const activeSpeakerId = pendingInput?.player_id || gameState?.current_speaker_id || null;
  const isHumanMode = mode === "human";

  // Badge state — exposed so PlayerCard can render the sheriff badge and the
  // "竞选警长" marker for active candidates during DAY_BADGE_* phases. We
  // resolve these once per render instead of inside every map() iteration.
  const sheriffId: string | null = (gameState as any)?.badge?.holder_id || null;
  const badgeCandidateIds: string[] = Array.isArray((gameState as any)?.badge?.candidates)
    ? (gameState as any).badge.candidates
    : [];

  // Find human player's role and wolf teammates for PlayerCard own-role display
  const humanPlayer = useMemo(() => (gameState?.players || []).find((p: any) => p.seat === humanSeat), [gameState?.players, humanSeat]);
  const wolfTeammates = useMemo(() => {
    if (!isHumanMode || humanPlayer?.alignment !== "wolf") return undefined;
    return (gameState?.players || [])
      .filter((p: any) => p.alignment === "wolf" && p.seat !== humanSeat)
      .map((p: any) => p.name);
  }, [gameState?.players, humanPlayer, humanSeat, isHumanMode]);

  function ph(from: number, to: number) {
    const arr = [];
    for (let s = from; s <= to; s++) arr.push({ id: `ph-${s}`, seat: s, name: language === "zh" ? `玩家 ${s}` : `Player ${s}`, alive: true, is_ai: s !== humanSeat } as any);
    return arr;
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden night-stars" data-phase-aware
      style={{ background: "var(--color-bg)" }}>

      {/* Phase Announcement Overlay */}
      {announcePhase && (
        <PhaseAnnouncement
          phase={announcePhase.phase}
          prevPhase={announcePhase.prev}
          onDone={() => setAnnouncePhase(null)}
        />
      )}

      {isNight && (
        <div className="fixed inset-0 pointer-events-none z-0 transition-opacity duration-800"
          style={{ background: "radial-gradient(ellipse at 50% 0%, rgba(25,25,35,0.25) 0%, rgba(0,0,0,0.55) 100%)", opacity: 1 }} />
      )}

      {/* Header */}
      <header className="relative z-10 flex items-center gap-3 px-4 md:px-6 py-2.5 border-b flex-wrap" data-phase-aware
        style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
        <div className="flex items-center gap-3">
          <span className="font-display text-lg font-semibold text-primary">AI Werewolf</span>
          <span className="text-xs text-text-sub">{t("roomLabel", language)}: {truncate(roomId, 8)}</span>
        </div>
        <div className="flex items-center gap-2 mx-auto">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            className={isNight ? "text-primary" : "text-accent"}>
            {isNight ? <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /> :
              <><circle cx="12" cy="12" r="5" /><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" /></>}
          </svg>
          <span className="font-display text-lg font-bold text-textPrimary">
            {gameState ? (language === "zh" ? `第${gameState.day}天` : `Day ${gameState.day}`) : t("statusReady", language)}
            {gameState?.winner && <span className="ml-2 text-accent"> - {gameState.winner === "village" ? t("village", language) : t("wolf", language)}</span>}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-button border overflow-hidden" style={{ borderColor: "var(--color-border)" }}>
            <button onClick={() => setViewMode(ViewMode.PUBLIC)} className={`px-2 py-1 text-xs font-medium ${viewMode === ViewMode.PUBLIC ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>{t("public", language)}</button>
            <button onClick={() => setViewMode(ViewMode.MODERATOR)} className={`px-2 py-1 text-xs font-medium ${viewMode === ViewMode.MODERATOR ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>{t("private", language)}</button>
          </div>
          {!isPlaying && !isHumanMode && !gameState?.winner && <Button size="sm" onClick={runGame}>{t("run", language)}</Button>}
          {!isPlaying && isHumanMode && !gameState?.winner && <Button size="sm" onClick={startHumanGame}>{t("run", language)}</Button>}
          <div className="flex rounded-button border overflow-hidden" style={{ borderColor: "var(--color-border)" }}>
            <button onClick={() => setLanguage(Language.ZH)} className={`px-2 py-1 text-xs font-medium ${language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>中</button>
            <button onClick={() => setLanguage(Language.EN)} className={`px-2 py-1 text-xs font-medium ${language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>EN</button>
          </div>
        </div>
      </header>

      {/* Main */}
      <div className="flex-1 flex relative z-10 overflow-hidden">
        <aside className="hidden lg:flex flex-col gap-2 p-3 w-[21%] min-w-[150px] overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
          style={{ borderRight: `1px solid var(--color-border)` }}>
          {(leftPlayers.length > 0 ? leftPlayers : ph(1, Math.ceil((gameState?.players?.length || 7) / 2))).map((p: any, i: number) => (
            <PlayerCard key={p.id || i} player={p}
              isSpeaking={pendingInput?.player_id === p.id}
              isThinking={!pendingInput && activeSpeakerId === p.id}
              isSheriff={sheriffId === p.id}
              isBadgeCandidate={badgeCandidateIds.includes(p.id)}
              showOwnRole={isHumanMode && p.seat === humanSeat}
              wolfTeammates={isHumanMode && p.seat === humanSeat ? wolfTeammates : undefined}
            />
          ))}
        </aside>

        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <div className="px-5 py-2.5 border-b text-base text-text-sub flex items-center gap-3 font-medium"
            style={{ background: "var(--color-card)", borderColor: "var(--color-border)" }}>
            <span className="font-semibold">{statusTitle}</span>
            {gameState?.phase && <span>· {tPhase(gameState.phase, language)}</span>}
            <span>· {t("aliveCount", language)}: {aliveCount}/{gameState?.players?.length || 0}</span>
            <span>· {t("events", language)}: {gameState?.event_count || 0}</span>
          </div>
          <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-3">
            {gameState?.events?.length ? (
              Object.keys(dayBlocks).sort((a, b) => Number(a) - Number(b)).map((dk) => {
                const dayEvents = dayBlocks[Number(dk)];
                // Find deaths for day header
                const deaths = dayEvents.filter((e: any) =>
                  e.type === EventType.PLAYER_DIED || e.type === EventType.HUNTER_SHOT || e.type === EventType.WHITE_WOLF_KING_BOOM
                );
                return (
                  <div key={dk} className="mb-5">
                    {/* Day header */}
                    <div className="flex items-center gap-3 mb-3 pb-2 border-b" style={{ borderColor: "var(--color-border)" }}>
                      <span className="font-display text-2xl font-bold text-primary">D{dk}</span>
                      {deaths.length > 0 && (
                        <span className="text-xs text-danger truncate">
                          {deaths.map((d: any) => d.payload.player_name || d.payload.target_name || "?").join(" · ")} {language === "zh" ? "出局" : "died"}
                        </span>
                      )}
                    </div>
                    {/* Events */}
                    <div className="space-y-0.5">
                      {dayEvents.map((ev: any, i: number) => {
                        const isSystem = ev.type === EventType.PHASE_CHANGED || ev.type === EventType.GAME_START
                          || ev.type === EventType.GAME_END || ev.type === EventType.SYSTEM_MESSAGE;
                        const isChat = ev.type === EventType.CHAT_MESSAGE;

                        if (isSystem) {
                          const iconMap: Record<string, string> = {
                            GAME_START: "\u{1F3AE}", PHASE_CHANGED: "", GAME_END: "\u{1F3C6}", SYSTEM_MESSAGE: "\u{1F4E2}",
                          };
                          const msg = ev.payload.message ?? (ev.payload.phase ? tPhase(ev.payload.phase, language) : "");
                          const icon = iconMap[ev.type] || "";
                          return (
                            <ChatBubble
                              key={ev.id || i}
                              speakerName=""
                              content={icon ? `${icon} ${msg}` : msg}
                              isSystem
                            />
                          );
                        }
                        if (isChat) {
                          return (
                            <ChatBubble
                              key={ev.id || i}
                              speakerName={ev.payload.actor_name || "?"}
                              content={ev.payload.speech || ""}
                              isOwn={isHumanMode && ev.payload.actor_id?.startsWith(`P${humanSeat}-`)}
                              phaseLabel={tPhase(ev.phase, language)}
                            />
                          );
                        }
                        return <EventItem key={ev.id || i} event={ev} index={i} />;
                      })}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center py-20">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"
                  className="text-text-sub/25 mb-5"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" /></svg>
                <p className="font-display text-lg text-textPrimary mb-2">{t("readyHint", language)}</p>
                <p className="text-sm text-text-sub">{t("statusHint", language)}</p>
              </div>
            )}
          </div>
          {pendingInput && (
            <ActionPanel pendingInput={pendingInput} onAction={handleHumanAction} language={language}
              votes={gameState?.votes}
              players={gameState?.players}
            />
          )}
        </main>

        <aside className="hidden lg:flex flex-col gap-2 p-3 w-[21%] min-w-[150px] overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]"
          style={{ borderLeft: `1px solid var(--color-border)` }}>
          {(rightPlayers.length > 0 ? rightPlayers : ph(splitPoint + 1, gameState?.players?.length || 7)).map((p: any, i: number) => (
            <PlayerCard key={p.id || i} player={p}
              isSpeaking={pendingInput?.player_id === p.id}
              isThinking={!pendingInput && activeSpeakerId === p.id}
              isSheriff={sheriffId === p.id}
              isBadgeCandidate={badgeCandidateIds.includes(p.id)}
              showOwnRole={isHumanMode && p.seat === humanSeat}
              wolfTeammates={isHumanMode && p.seat === humanSeat ? wolfTeammates : undefined}
            />
          ))}
        </aside>
      </div>

      <div className="lg:hidden relative z-10 flex gap-2 overflow-x-auto px-4 py-2">
        {((gameState?.players?.length || 0) > 0 ? gameState!.players : ph(1, gameState?.players?.length || 7)).map((p: any, i: number) => (
          <div key={p.id || i} className="flex-shrink-0 w-[100px]"><PlayerCard player={p}
            isSpeaking={pendingInput?.player_id === p.id}
            isThinking={!pendingInput && activeSpeakerId === p.id}
            isSheriff={sheriffId === p.id}
            isBadgeCandidate={badgeCandidateIds.includes(p.id)}
            showOwnRole={isHumanMode && p.seat === humanSeat}
            wolfTeammates={isHumanMode && p.seat === humanSeat ? wolfTeammates : undefined}
          /></div>
        ))}
      </div>

      {/* ====== Game End: Floating Ball + Expandable Panel ====== */}
      {gameState?.winner && (
        <>
          {/* Floating ball — always visible after game ends */}
          {!showWinnerPanel && (
            <button
              onClick={() => { if (!dragRef.current.moved) setShowWinnerPanel(true); }}
              onPointerDown={(e) => {
                const el = e.currentTarget;
                const rect = el.getBoundingClientRect();
                const ox = ballPos?.x ?? rect.left;
                const oy = ballPos?.y ?? rect.top;
                dragRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, origX: ox, origY: oy, moved: false };
                el.setPointerCapture(e.pointerId);
              }}
              onPointerMove={(e) => {
                if (!dragRef.current.dragging) return;
                const dx = e.clientX - dragRef.current.startX;
                const dy = e.clientY - dragRef.current.startY;
                if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragRef.current.moved = true;
                if (dragRef.current.moved) {
                  setBallPos({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
                }
              }}
              onPointerUp={() => { dragRef.current.dragging = false; }}
              className="fixed z-50 flex items-center gap-2.5 pl-3 pr-4 py-2.5 rounded-full animate-scale-in cursor-grab active:cursor-grabbing border-0 shadow-[0_4px_24px_rgba(0,0,0,0.12)] hover:shadow-[0_6px_32px_rgba(0,0,0,0.16)] select-none transition-shadow duration-200"
              style={{
                background: "var(--color-card)",
                border: "1px solid var(--color-border)",
                ...(ballPos
                  ? { left: ballPos.x, top: ballPos.y }
                  : { right: 24, bottom: 24 }),
              }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
                className="text-accent animate-breathe">
                <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C7 4 8 7 8 7" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5C17 4 16 7 16 7" />
                <path d="M4 22h16" /><path d="M10 22V8c0-1.1.9-2 2-2s2 .9 2 2v14" /><path d="M8 12h8" />
              </svg>
              <div className="text-left leading-tight">
                <p className="text-[10px] text-text-sub">{language === "zh" ? "游戏结束" : "Game Over"}</p>
                <p className={`text-sm font-bold ${gameState.winner === "village" ? "text-success" : "text-danger"}`}>
                  {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
                  {language === "zh" ? "获胜" : " Wins"}
                </p>
              </div>
            </button>
          )}

          {/* Expanded panel */}
          {showWinnerPanel && (
            <div className="fixed inset-0 z-50 flex items-center justify-center"
              style={{ background: "rgba(0,0,0,0.45)", backdropFilter: "blur(3px)" }}
              onClick={() => setShowWinnerPanel(false)}>
              <div className="text-center animate-scale-in px-6 py-8 rounded-card max-w-sm w-full mx-4"
                style={{ background: "var(--color-card)", boxShadow: "0 16px 64px rgba(0,0,0,0.25)" }}
                onClick={(e) => e.stopPropagation()}>
                {/* Trophy */}
                <div className="mb-3">
                  <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" className="mx-auto text-accent">
                    <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C7 4 8 7 8 7" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5C17 4 16 7 16 7" />
                    <path d="M4 22h16" /><path d="M10 22V8c0-1.1.9-2 2-2s2 .9 2 2v14" /><path d="M8 12h8" />
                  </svg>
                </div>
                <p className="text-sm text-text-sub mb-2">{language === "zh" ? "游戏结束" : "Game Over"}</p>
                <h2 className={`font-display text-3xl font-bold mb-1 ${gameState.winner === "village" ? "text-success" : "text-danger"}`}>
                  {gameState.winner === "village" ? t("village", language) : t("wolf", language)}
                </h2>
                <p className="font-display text-textPrimary mb-5">
                  {gameState.winner === "village"
                    ? (language === "zh" ? "好人阵营获胜" : "Village Wins")
                    : (language === "zh" ? "狼人阵营获胜" : "Wolves Win")}
                </p>

                {/* Stats */}
                <div className="grid grid-cols-3 gap-3 mb-5 text-center">
                  {[
                    [String(gameState.day), language === "zh" ? "总天数" : "Days"],
                    [String(aliveCount), language === "zh" ? "存活" : "Alive"],
                    [String(gameState.event_count || 0), language === "zh" ? "事件" : "Events"],
                  ].map(([val, label]) => (
                    <div key={label}>
                      <p className="font-display text-2xl font-bold text-primary">{val}</p>
                      <p className="text-xs text-text-sub">{label}</p>
                    </div>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex gap-3 mb-3">
                  <Button variant="ghost" onClick={() => router.push("/")} className="flex-1">
                    {language === "zh" ? "返回大厅" : "Lobby"}
                  </Button>
                  <Button onClick={() => router.push("/")} className="flex-1">
                    {language === "zh" ? "再来一局" : "Play Again"}
                  </Button>
                </div>

                {/* Collapse button */}
                <button
                  onClick={() => setShowWinnerPanel(false)}
                  className="text-xs text-text-sub underline hover:text-textPrimary transition-colors"
                >
                  {language === "zh" ? "收起面板，留在页面" : "Dismiss, stay on page"}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
