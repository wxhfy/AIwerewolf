"use client";

import { useRef, useState } from "react";
import { AgentType, GameState, Language, RoomRecord } from "@/types";
import { t } from "@/lib/i18n";
import { apiUrl } from "@/lib/api";
import { startAiMatch } from "@/lib/gameApi";

interface UseRoomStreamOptions {
  roomId: string;
  seed: number;
  speed: number;
  agentType: AgentType;
  language: Language;
  getGameState: () => GameState | null;
  setRoom: (room: RoomRecord | null) => void;
  setGameState: (state: GameState | null) => void;
  setIsPlaying: (playing: boolean) => void;
  setStatusTitle: (title: string) => void;
  showPrivate?: boolean;
  onForbidden?: () => void;
}

export function useRoomStream({
  roomId,
  language,
  getGameState,
  setGameState,
  setIsPlaying,
  setStatusTitle,
  showPrivate = false,
  onForbidden,
}: UseRoomStreamOptions) {
  const sourceRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef(-1);
  const lastProgressSeqRef = useRef(-1);
  const matchIdRef = useRef<string | null>(null);
  const isCompleteRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isReconnecting, setIsReconnecting] = useState(false);

  function closeStream() {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    sourceRef.current?.close();
    sourceRef.current = null;
    setIsReconnecting(false);
  }

  function isStreamActive() {
    return sourceRef.current != null;
  }

  function applySnapshot(state: GameState) {
    setIsReconnecting(false);
    const incomingSeq = Number(state.seq || state.last_event?.seq || state.event_count || 0);
    const progressSeq = Number((state as any).progress_seq || 0);
    if (matchIdRef.current !== state.id) {
      matchIdRef.current = state.id;
      lastSeqRef.current = -1;
      lastProgressSeqRef.current = -1;
      isCompleteRef.current = false;
    }
    // Accept same event seq when runtime progress advances (LLM thinking UX).
    if (incomingSeq < lastSeqRef.current) return;
    if (incomingSeq === lastSeqRef.current && progressSeq <= lastProgressSeqRef.current) return;
    lastSeqRef.current = incomingSeq;
    lastProgressSeqRef.current = progressSeq;
    setGameState(state);
    if (state.winner) {
      isCompleteRef.current = true;
      setIsPlaying(false);
      setStatusTitle(t("statusLoaded", language));
    } else {
      setIsPlaying(true);
      setStatusTitle(t("statusStreaming", language));
    }
  }

  function createSource(matchId: string, afterSeq: number) {
    const params = new URLSearchParams({
      after_seq: String(Math.max(0, afterSeq)),
      moderator: showPrivate ? "true" : "false",
    });
    const source = new EventSource(apiUrl(`/api/matches/${matchId}/stream?${params.toString()}`));
    sourceRef.current = source;

    source.onopen = () => {
      setIsReconnecting(false);
    };

    source.addEventListener("snapshot", (event) => {
      try {
        applySnapshot(JSON.parse((event as MessageEvent<string>).data) as GameState);
      } catch {
        setStatusTitle(t("statusError", language));
      }
    });

    source.addEventListener("complete", () => {
      isCompleteRef.current = true;
      setIsPlaying(false);
      setStatusTitle(t("statusLoaded", language));
      closeStream();
    });

    source.onerror = () => {
      if (isCompleteRef.current) return;
      // When connection drops or errors, indicate reconnection and schedule reconnect with after_seq
      setIsReconnecting(true);
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      reconnectTimerRef.current = setTimeout(() => {
        if (isCompleteRef.current) return;
        source.close();
        if (matchIdRef.current) {
          createSource(matchIdRef.current, Math.max(0, lastSeqRef.current));
        }
      }, 1500);
    };
  }

  function attachMatchStream(matchId: string, seedSnapshot?: GameState | null) {
    if (!matchId) return;
    if (sourceRef.current && matchIdRef.current === matchId) {
      if (seedSnapshot) applySnapshot(seedSnapshot);
      return;
    }
    closeStream();
    matchIdRef.current = matchId;
    lastSeqRef.current = -1;
    lastProgressSeqRef.current = -1;
    isCompleteRef.current = false;
    if (seedSnapshot) applySnapshot(seedSnapshot);

    createSource(matchId, lastSeqRef.current);
  }

  async function runGame() {
    closeStream();
    isCompleteRef.current = false;
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    if (getGameState()?.winner) setGameState(null);

    try {
      const started = await startAiMatch(roomId, showPrivate);
      attachMatchStream(started.match_id, started.snapshot);
    } catch (err: any) {
      if (showPrivate && (err?.status === 403 || String(err?.message || "").includes("403"))) {
        onForbidden?.();
        try {
          const started = await startAiMatch(roomId, false);
          attachMatchStream(started.match_id, started.snapshot);
          return;
        } catch {
          // fallback also failed
        }
      }
      setIsPlaying(false);
      setStatusTitle(t("statusError", language));
      closeStream();
    }
  }

  return { runGame, closeStream, isStreamActive, attachMatchStream, isReconnecting };
}
