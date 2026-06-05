"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { fetchRoom, startRoom, submitHumanAction } from "@/lib/gameApi";
import { t } from "@/lib/i18n";
import { placeholderPlayers } from "@/lib/gameView";
import { isMergedChatSegment } from "@/lib/eventFilter";
import { EventType, Player } from "@/types";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import { useGameDerivedState } from "@/hooks/useGameDerivedState";
import { usePhaseTransition } from "@/hooks/usePhaseTransition";
import { useRoomStream } from "@/hooks/useRoomStream";
import { useVoteDisplay } from "@/hooks/useVoteDisplay";

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
  const winnerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-open result modal when game ends — delay to let end animation finish first
  useEffect(() => {
    if (gameState?.winner && !winnerShownRef.current) {
      winnerShownRef.current = true;
      // enterEndPhase() 动画需要 ~1400ms 完成，延迟 1500ms 再弹窗避免重叠
      winnerTimerRef.current = setTimeout(() => {
        setShowWinnerPanel(true);
        winnerTimerRef.current = null;
      }, 1500);
    }
    if (!gameState?.winner) {
      winnerShownRef.current = false;
      if (winnerTimerRef.current) {
        clearTimeout(winnerTimerRef.current);
        winnerTimerRef.current = null;
      }
      setShowWinnerPanel(false);
    }
    return () => {
      if (winnerTimerRef.current) {
        clearTimeout(winnerTimerRef.current);
        winnerTimerRef.current = null;
      }
    };
  }, [gameState?.winner]);
  const [ballPos, setBallPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, origX: 0, origY: 0, moved: false });
  const [statusTitle, setStatusTitle] = useState(gameState?.winner ? t("statusLoaded", language) : t("statusReady", language));
  const latestGameStateRef = useRef(gameState);
  const autoStartedRef = useRef(false);
  const isHumanMode = mode === "human";
  const [fetchError, setFetchError] = useState<string | null>(null);

  // ── Typewriter-driven display phase ─────────────────────────────
  const [completedIds] = useState<Set<string>>(() => new Set());
  const completedIdsRef = useRef(completedIds);
  const [completedTick, setCompletedTick] = useState(0);

  // ── Phase timeout: 防止某阶段因缺少事件而永久卡住 ──────────────
  const phaseFirstSeenRef = useRef<{ phase: string; timestamp: number }>({ phase: "", timestamp: 0 });
  const [phaseTimeoutTick, setPhaseTimeoutTick] = useState(0);
  const PHASE_TIMEOUT_MS = 15000; // 15s 无进展则强制放行
  const phaseTimeoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 记录触发超时时的阻塞阶段，防止竞态：超时回调可能在阶段已变化后执行
  const stuckPhaseRef = useRef<string>("");

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
  const voteDisplay = useVoteDisplay(gameState, completedIdsRef.current, completedTick, phase.isTransitioning);

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

  // 眨眼 + settling 结束后，对齐缓冲的最新状态。
  // flushResultRef 在 _finishBlink() settling timer 中写入，紧跟着 setIsTransitioning(false)。
  // 必须同时等 isBlinking 和 isTransitioning 都为 false 才 flush，
  // 否则 settling 期内事件会提前渲染，导致"守卫请睁眼"早于背景变黑出现。
  useEffect(() => {
    const pending = phase.flushResultRef.current;
    if (pending && !phase.isBlinking && !phase.isTransitioning) {
      phase.flushResultRef.current = null;
      setGameState(pending);
    }
  }, [phase.isBlinking, phase.isTransitioning]);

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

  // ── Phase timeout: force-complete stuck CHAT_MESSAGE events ──────
  // 当 phaseTimeoutTick 变化时，把超时时刻的阻塞阶段未完成 CHAT_MESSAGE 强制完成
  useEffect(() => {
    if (phaseTimeoutTick === 0) return;
    const events = gameState?.events;
    if (!events) return;
    const targetPhase = stuckPhaseRef.current;
    if (!targetPhase) return;
    let changed = false;
    for (const e of events) {
      if (e.type === "CHAT_MESSAGE" && e.phase === targetPhase && !completedIdsRef.current.has(e.id)) {
        completedIdsRef.current.add(e.id);
        changed = true;
      }
    }
    if (changed) setCompletedTick((n) => n + 1);
  }, [phaseTimeoutTick]);

  // Display phase: the phase that the user is currently EXPERIENCING via
  // typewriter — NOT the raw gameState.phase.  It only advances after all
  // chat messages from the previous phase have been fully typed out.
  // 游戏结束后直接返回真实阶段，不再追踪打字机进度。
  //
  // ⚠️  合并段跳过：EventTimeline.mergeConsecutiveChats 会把同玩家同 phase 的
  // 连续 CHAT_MESSAGE 合并成一个气泡（只保留第一个 segment 的 ID）。
  // completedIds 里只有第一个 segment 的 ID，后续 segment 永远不会被标记完成。
  // 因此 displayPhase 必须在遍历时跳过这些合并段，否则会被第二段永久阻塞。
  const displayPhase = useMemo(() => {
    const events = gameState?.events;
    if (!events) return gameState?.phase;
    if (gameState?.winner) return gameState?.phase;
    const completed = completedIdsRef.current;

    // Find the phase of the earliest uncompleted CHAT_MESSAGE,
    // skipping segments that mergeConsecutiveChats would collapse.
    let prevActor = "";
    let prevPhase = "";
    let blockingPhase: string | undefined;
    for (const e of events) {
      if (e.type === EventType.CHAT_MESSAGE) {
        if (isMergedChatSegment(e, prevActor, prevPhase)) continue;
        prevActor = (e.payload as any)?.actor_id || "";
        prevPhase = e.phase || "";
        if (!completed.has(e.id)) {
          blockingPhase = e.phase;
          break;
        }
      } else {
        prevActor = "";
        prevPhase = "";
      }
    }

    return blockingPhase || gameState?.phase;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gameState?.events, gameState?.phase, gameState?.winner, completedTick, phaseTimeoutTick]);

  // ── Phase timeout timer management (side effect, NOT in useMemo) ──
  useEffect(() => {
    const currentBlockingPhase = displayPhase || "";
    const tracked = phaseFirstSeenRef.current;
    const now = Date.now();

    if (currentBlockingPhase !== tracked.phase) {
      tracked.phase = currentBlockingPhase;
      tracked.timestamp = now;
      stuckPhaseRef.current = currentBlockingPhase;
      if (phaseTimeoutTimerRef.current) clearTimeout(phaseTimeoutTimerRef.current);
      phaseTimeoutTimerRef.current = setTimeout(() => {
        setPhaseTimeoutTick((n) => n + 1);
      }, PHASE_TIMEOUT_MS);
    }

    return () => {
      if (phaseTimeoutTimerRef.current) clearTimeout(phaseTimeoutTimerRef.current);
    };
  }, [displayPhase]);

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
    voteDisplay,
    // Blink transition passthrough
    isBlinking: phase.isBlinking,
    isTransitioning: phase.isTransitioning,
    blinkPhase: phase.blinkPhase,
    onBlinkCloseComplete: phase.onBlinkCloseComplete,
    onBlinkPauseComplete: phase.onBlinkPauseComplete,
    onBlinkOpenComplete: phase.onBlinkOpenComplete,
  };
}
