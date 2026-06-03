"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { fetchRoom, startRoom, submitHumanAction } from "@/lib/gameApi";
import { t } from "@/lib/i18n";
import { placeholderPlayers } from "@/lib/gameView";
import { Player } from "@/types";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useGameDerivedState } from "@/hooks/useGameDerivedState";
import { usePhaseTransition } from "@/hooks/usePhaseTransition";
import { useRoomStream } from "@/hooks/useRoomStream";

export function useGamePageController(roomId: string) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode") || "ai";
  const humanSeat = Number(searchParams.get("human_seat") || 1);
  const {
    language, setLanguage, viewMode, setViewMode, agentType,
    room, setRoom, gameState, setGameState, isPlaying, setIsPlaying,
    speed, seed,
  } = useAppContext();

  const [showWinnerPanel, setShowWinnerPanel] = useState(false);
  const winnerShownRef = useRef(false);

  // Auto-open result modal when game ends
  useEffect(() => {
    if (gameState?.winner && !winnerShownRef.current) {
      winnerShownRef.current = true;
      setShowWinnerPanel(true);
    }
    if (!gameState?.winner) {
      winnerShownRef.current = false;
    }
  }, [gameState?.winner]);
  const [ballPos, setBallPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, origX: 0, origY: 0, moved: false });
  const [statusTitle, setStatusTitle] = useState(gameState?.winner ? t("statusLoaded", language) : t("statusReady", language));
  const latestGameStateRef = useRef(gameState);
  const autoStartedRef = useRef(false);
  const isHumanMode = mode === "human";
  const [fetchError, setFetchError] = useState<string | null>(null);

  // ── Typewriter-driven display phase ─────────────────────────────
  // Tracks which CHAT_MESSAGE events have been fully typed out.
  // The "display phase" only advances once all messages from the
  // current phase are done.
  const [completedIds] = useState<Set<string>>(() => new Set());
  const completedIdsRef = useRef(completedIds);
  const [completedTick, setCompletedTick] = useState(0);

  const onChatComplete = useCallback((eventId: string) => {
    completedIdsRef.current.add(eventId);
    setCompletedTick((n) => n + 1);
  }, []);

  const sessionKey = roomId;
  const phase = usePhaseTransition(sessionKey, gameState, Boolean(gameState?.winner));
  const scroll = useAutoScroll(gameState?.events?.length);
  // 使用 displayGameState：眨眼期间冻结，动画结束后对齐最新
  const effectiveState = phase.displayGameState;
  const derived = useGameDerivedState(effectiveState, humanSeat, isHumanMode, completedIdsRef.current, completedTick);

  const roomStream = useRoomStream({
    roomId,
    seed,
    speed,
    agentType,
    language,
    getGameState: () => latestGameStateRef.current,
    setRoom,
    setGameState,
    setIsPlaying,
    setStatusTitle,
    getIsBlinking: phase.getIsBlinking,
    bufferSnapshot: phase.bufferSnapshot,
  });

  // 眨眼结束后，对齐缓冲的最新状态
  // flushResultRef 在 _finishBlink() 中同步写入，紧跟着 setIsBlinking(false)，
  // 所以 React 因 isBlinking 变化触发本 effect 时 ref 一定已就绪。
  useEffect(() => {
    const pending = phase.flushResultRef.current;
    if (pending && !phase.isBlinking) {
      phase.flushResultRef.current = null;
      setGameState(pending);
    }
  }, [phase.isBlinking]);

  useEffect(() => {
    latestGameStateRef.current = gameState;
  }, [gameState]);

  useEffect(() => {
    return () => roomStream.closeStream();
  }, [roomId]);

  useEffect(() => {
    if (mode === "human" && !isPlaying && !gameState?.pending_input && !gameState?.winner && !autoStartedRef.current) {
      autoStartedRef.current = true;
      startHumanGame();
    }
  }, [mode, roomId, gameState?.id]);

  useEffect(() => {
    if (!gameState) return;
    if (gameState.winner) {
      setStatusTitle(t("statusLoaded", language));
      setIsPlaying(false);
    } else if (gameState.pending_input) {
      setStatusTitle(t("statusStreaming", language));
      setIsPlaying(true);
    }
  }, [gameState?.id]);

  function retryRoom() {
    setFetchError(null);
    const controller = new AbortController();
    fetchRoom(roomId).then((nextRoom) => {
      if (controller.signal.aborted) return;
      if (nextRoom) { setRoom(nextRoom); setFetchError(null); }
    }).catch((e) => {
      if (controller.signal.aborted) return;
      setFetchError(String(e?.message || e || "Failed to load room"));
    });
  }

  useEffect(() => {
    if (!room || room.id !== roomId) {
      retryRoom();
    }
  }, [roomId]);

  useEffect(() => {
    if (autoStartedRef.current) return;
    if (mode !== "ai") return;
    if (gameState?.winner) return;
    if (isPlaying) return;
    if (roomStream.isStreamActive()) return;
    const id = setTimeout(() => {
      autoStartedRef.current = true;
      runGame();
    }, 200);
    return () => clearTimeout(id);
  }, [mode, roomId]);

  function runGame() {
    if (mode === "human") {
      startHumanGame();
      return;
    }
    roomStream.runGame();
  }

  async function startHumanGame() {
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    setGameState(null);
    try {
      const snapshot = await startRoom(roomId);
      setGameState(snapshot);
      if (snapshot.winner) {
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
      }
    } catch {
      setIsPlaying(false);
      setStatusTitle(t("statusError", language));
    }
  }

  async function handleHumanAction(data: { target_id?: string | null; speech?: string | null; save?: boolean }) {
    setFetchError(null);
    try {
      setIsPlaying(true);
      const snapshot = await submitHumanAction(roomId, data);
      setGameState(snapshot);
      if (snapshot.winner) {
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
      }
    } catch (e) {
      setFetchError(String((e as any)?.message || e || "Action failed"));
      setStatusTitle(t("statusError", language));
      setIsPlaying(false);
    }
  }

  function placeholder(from: number, to: number): Player[] {
    return placeholderPlayers(from, to, language, humanSeat);
  }

  // Display phase: the phase that the user is currently EXPERIENCING via
  // typewriter — NOT the raw gameState.phase.  It only advances after all
  // chat messages from the previous phase have been fully typed out.
  // 游戏结束后直接返回真实阶段，不再追踪打字机进度。
  const displayPhase = useMemo(() => {
    const events = gameState?.events;
    if (!events) return gameState?.phase;
    if (gameState?.winner) return gameState?.phase;
    const completed = completedIdsRef.current;
    // Find the phase of the earliest uncompleted CHAT_MESSAGE
    for (const e of events) {
      if (e.type === "CHAT_MESSAGE" && !completed.has(e.id)) {
        return e.phase;
      }
    }
    return gameState?.phase;
  }, [gameState?.events, gameState?.phase, gameState?.winner, completedTick]);

  return {
    router,
    roomId,
    language,
    setLanguage,
    viewMode,
    setViewMode,
    gameState,
    isPlaying,
    isHumanMode,
    humanSeat,
    showWinnerPanel,
    setShowWinnerPanel,
    ballPos,
    setBallPos,
    dragRef,
    statusTitle,
    phase,
    scroll,
    derived,
    runGame,
    startHumanGame,
    handleHumanAction,
    placeholder,
    fetchError,
    retryRoom,
    displayPhase,
    completedIdsRef,
    onChatComplete,
    // Blink transition passthrough
    isBlinking: phase.isBlinking,
    blinkPhase: phase.blinkPhase,
    onBlinkCloseComplete: phase.onBlinkCloseComplete,
    onBlinkPauseComplete: phase.onBlinkPauseComplete,
    onBlinkOpenComplete: phase.onBlinkOpenComplete,
  };
}
