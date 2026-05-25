"use client";

import { useEffect, useRef, useState } from "react";
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
  const [ballPos, setBallPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, origX: 0, origY: 0, moved: false });
  const [statusTitle, setStatusTitle] = useState(gameState?.winner ? t("statusLoaded", language) : t("statusReady", language));
  const latestGameStateRef = useRef(gameState);
  const autoStartedRef = useRef(false);
  const isHumanMode = mode === "human";

  const sessionKey = `${roomId}:${gameState?.id || "no-game"}`;
  const phase = usePhaseTransition(sessionKey, gameState?.phase, Boolean(gameState?.winner));
  const scroll = useAutoScroll(gameState?.events?.length);
  const derived = useGameDerivedState(gameState, humanSeat, isHumanMode);

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
  });

  useEffect(() => {
    latestGameStateRef.current = gameState;
  }, [gameState]);

  useEffect(() => {
    return () => roomStream.closeStream();
  }, [roomId]);

  useEffect(() => {
    if (mode === "human" && !gameState && !isPlaying) startHumanGame();
  }, [mode, roomId]);

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

  useEffect(() => {
    if (!room || room.id !== roomId) {
      fetchRoom(roomId).then((nextRoom) => { if (nextRoom) setRoom(nextRoom); }).catch(() => {});
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
    try {
      const snapshot = await submitHumanAction(roomId, data);
      setGameState(snapshot);
      if (snapshot.winner) {
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
      }
    } catch {
      setStatusTitle(t("statusError", language));
    }
  }

  function placeholder(from: number, to: number): Player[] {
    return placeholderPlayers(from, to, language, humanSeat);
  }

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
  };
}
