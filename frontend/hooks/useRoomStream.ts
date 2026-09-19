"use client";

import { useRef } from "react";
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
}

export function useRoomStream({
  roomId,
  language,
  getGameState,
  setGameState,
  setIsPlaying,
  setStatusTitle,
  showPrivate = false,
}: UseRoomStreamOptions) {
  const sourceRef = useRef<EventSource | null>(null);
  const lastSeqRef = useRef(-1);
  const matchIdRef = useRef<string | null>(null);

  function closeStream() {
    sourceRef.current?.close();
    sourceRef.current = null;
  }

  function isStreamActive() {
    return sourceRef.current != null;
  }

  function applySnapshot(state: GameState) {
    const incomingSeq = Number(state.seq || state.last_event?.seq || state.event_count || 0);
    if (matchIdRef.current !== state.id) {
      matchIdRef.current = state.id;
      lastSeqRef.current = -1;
    }
    if (incomingSeq <= lastSeqRef.current) return;
    lastSeqRef.current = incomingSeq;
    setGameState(state);
  }

  async function runGame() {
    closeStream();
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    if (getGameState()?.winner) setGameState(null);

    try {
      const started = await startAiMatch(roomId, showPrivate);
      matchIdRef.current = started.match_id;
      lastSeqRef.current = -1;
      applySnapshot(started.snapshot);

      const params = new URLSearchParams({
        after_seq: String(Math.max(0, lastSeqRef.current)),
        moderator: showPrivate ? "true" : "false",
      });
      const source = new EventSource(apiUrl(`/api/matches/${started.match_id}/stream?${params.toString()}`));
      sourceRef.current = source;

      source.addEventListener("snapshot", (event) => {
        try {
          applySnapshot(JSON.parse((event as MessageEvent<string>).data) as GameState);
        } catch {
          setStatusTitle(t("statusError", language));
        }
      });

      source.addEventListener("complete", () => {
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
        closeStream();
      });

      source.onerror = () => {
        if (source.readyState === EventSource.CLOSED) {
          setIsPlaying(false);
          setStatusTitle(t("statusError", language));
        }
      };
    } catch {
      setIsPlaying(false);
      setStatusTitle(t("statusError", language));
      closeStream();
    }
  }

  return { runGame, closeStream, isStreamActive };
}
