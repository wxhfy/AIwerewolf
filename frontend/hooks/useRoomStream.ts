"use client";

import { useRef } from "react";
import { AgentType, GameState, Language, RoomRecord, WebSocketMessage, WebSocketRequest } from "@/types";
import { t } from "@/lib/i18n";
import { wsUrl } from "@/lib/api";

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
  /** 眨眼转场期间返回 true，快照应缓冲而非直接更新 UI */
  getIsBlinking?: () => boolean;
  /** 眨眼转场期间缓冲快照（只保留最新一份） */
  bufferSnapshot?: (state: GameState) => void;
  showPrivate?: boolean;
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
  getIsBlinking,
  bufferSnapshot,
  showPrivate = false,
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

    const ws = new WebSocket(wsUrl(`/ws/rooms/${roomId}`));
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      ws.send(JSON.stringify({
        action: "start",
        seed,
        agent_type: agentType,
        show_private: showPrivate,
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
      // Task 3: Handle streaming tokens from live LLM output
      if (msg.type === "stream_token") {
        const state = getGameState();
        if (state && msg.delta) {
          // Emit a synthetic CHAT_MESSAGE-like event for real-time typewriter display
          const streamEvent = {
            type: "stream_token",
            player_id: msg.player_id,
            player_name: msg.player_name,
            delta: msg.delta,
          };
          // Dispatch custom event for components to consume
          if (typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("llm_stream_token", { detail: streamEvent }));
          }
        }
      }
      if (msg.type === "snapshot" && msg.state) {
        const s = msg.state;
        console.log(`[GAME] phase=${s.phase} day=${s.day} evt=${s.events?.length||0} alive=${s.alive_count} pending=${s.pending_input?.player_name||"none"} speaker=${s.current_speaker_id?.slice(0,10)||"none"}`);
        if (getIsBlinking?.() && bufferSnapshot) {
          bufferSnapshot(msg.state);
        } else {
          setGameState(msg.state);
        }
      }
      if (msg.type === "complete") {
        // 游戏结束：如果在眨眼期间，缓冲最终状态等 flush；
        // 如果不在眨眼期间，直接更新
        if (msg.state) {
          if (getIsBlinking?.() && bufferSnapshot) {
            bufferSnapshot(msg.state);
          } else {
            setGameState(msg.state);
          }
        }
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
        closeStream();
      }
      if (msg.type === "paused") {
        if (msg.state) {
          if (getIsBlinking?.() && bufferSnapshot) {
            bufferSnapshot(msg.state);
          } else {
            setGameState(msg.state);
          }
        }
        if (msg.room) setRoom(msg.room);
        setIsPlaying(false);
        setStatusTitle(language === Language.ZH ? "对局已暂停" : "Match paused");
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
