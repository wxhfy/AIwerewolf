"use client";

import { useRef } from "react";
import { AgentType, GameState, Language, RoomRecord, WebSocketMessage, WebSocketRequest } from "@/types";
import { t } from "@/lib/i18n";

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
}

export function useRoomStream({
  roomId,
  seed,
  speed,
  agentType,
  language,
  getGameState,
  setRoom,
  setGameState,
  setIsPlaying,
  setStatusTitle,
}: UseRoomStreamOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearReconnectTimer() {
    if (!reconnectTimerRef.current) return;
    clearTimeout(reconnectTimerRef.current);
    reconnectTimerRef.current = null;
  }

  function closeStream() {
    clearReconnectTimer();
    reconnectAttemptRef.current = 0;
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
  }

  function isStreamActive() {
    return wsRef.current != null;
  }

  function runGame() {
    closeStream();
    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    if (getGameState()?.winner) setGameState(null);

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/rooms/${roomId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      ws.send(JSON.stringify({
        action: "start",
        seed,
        agent_type: agentType,
        show_private: true,
        delay_ms: speed,
      } satisfies WebSocketRequest));
    };

    ws.onmessage = (event) => {
      let msg: WebSocketMessage;
      try {
        msg = JSON.parse(event.data) as WebSocketMessage;
      } catch {
        setStatusTitle(t("statusError", language));
        return;
      }

      if (msg.type === "room" && msg.room) setRoom(msg.room);
      if (msg.type === "snapshot" && msg.state) setGameState(msg.state);
      if (msg.type === "complete") {
        if (msg.state) setGameState(msg.state);
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
        closeStream();
      }
      if (msg.type === "error") {
        setIsPlaying(false);
        setStatusTitle(t("statusError", language));
      }
    };

    ws.onerror = () => setIsPlaying(false);

    ws.onclose = (event) => {
      setIsPlaying(false);
      const finished = getGameState()?.winner != null;
      const cleanClose = event.code === 1000 || event.code === 1001;
      if (finished || cleanClose || wsRef.current !== ws) return;

      const attempt = reconnectAttemptRef.current + 1;
      reconnectAttemptRef.current = attempt;
      const delay = Math.min(30000, 1000 * 2 ** Math.min(attempt - 1, 5));
      setStatusTitle(language === Language.ZH ? `连接断开，${Math.round(delay / 1000)} 秒后重连...` : `Reconnecting in ${Math.round(delay / 1000)}s…`);
      reconnectTimerRef.current = setTimeout(() => {
        if (wsRef.current === ws) runGame();
      }, delay);
    };
  }

  return { runGame, closeStream, isStreamActive };
}
