"use client";

import React, { useState, useEffect, useRef } from "react";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase, format } from "@/lib/i18n";
import { truncate } from "@/lib/utils";
import { WebSocketMessage, WebSocketRequest, Language, AgentType, ViewMode } from "@/types";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { PlayerCard } from "@/components/game/PlayerCard";
import { EventItem } from "@/components/game/EventItem";

export default function SpectatorPage() {
  const {
    language,
    setLanguage,
    viewMode,
    setViewMode,
    agentType,
    setAgentType,
    room,
    setRoom,
    gameState,
    setGameState,
    isPlaying,
    setIsPlaying,
    speed,
    setSpeed,
    seed,
    setSeed,
  } = useAppContext();

  const [statusText, setStatusText] = useState(t("statusHint", language));
  const [statusTitle, setStatusTitle] = useState(t("statusReady", language));
  const wsRef = useRef<WebSocket | null>(null);

  // 更新状态文本
  useEffect(() => {
    setStatusText(t("statusHint", language));
  }, [language]);

  // 创建房间
  async function createRoom() {
    try {
      setStatusTitle(t("statusLoading", language));
      setStatusText("");

      const response = await fetch(
        `/api/rooms?name=Demo+Room&seed=${seed}&player_count=7&agent_type=${agentType}`,
        {
          method: "POST",
          headers: { Accept: "application/json" },
        }
      );

      if (!response.ok) {
        throw new Error(`Failed to create room: ${response.status}`);
      }

      const roomData = await response.json();
      setRoom(roomData);
      setStatusTitle(t("roomReady", language));
      setStatusText(
        format(t("roomReadyDetail", language), {
          roomId: truncate(roomData.id),
          agentType: agentType === "llm" ? t("agentLlm", language) : t("agentHeuristic", language),
        })
      );
    } catch (error) {
      console.error("Failed to create room:", error);
      setStatusTitle(t("statusError", language));
      setStatusText(t("statusErrorDetail", language));
    }
  }

  // 通过 WebSocket 运行游戏
  function runGame() {
    if (!room) {
      createRoom().then(() => {
        setTimeout(runGame, 100);
      });
      return;
    }

    // 清理之前的连接
    if (wsRef.current) {
      wsRef.current.close();
    }

    setIsPlaying(true);
    setStatusTitle(t("statusStreaming", language));
    setGameState(null);

    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/rooms/${room.id}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      const request: WebSocketRequest = {
        action: "start",
        seed,
        agent_type: agentType,
        show_private: viewMode === ViewMode.MODERATOR,
        delay_ms: speed,
      };
      ws.send(JSON.stringify(request));
    };

    ws.onmessage = (event) => {
      const message: WebSocketMessage = JSON.parse(event.data);

      if (message.type === "room" && message.room) {
        setRoom(message.room);
      }

      if (message.type === "status") {
        // 状态更新
      }

      if (message.type === "snapshot" && message.state) {
        setGameState(message.state);
        setStatusText(
          format(t("statusStreamingDetail", language), {
            day: message.state.day,
            phase: tPhase(message.state.phase, language),
            events: message.state.event_count || 0,
          })
        );
      }

      if (message.type === "complete") {
        if (message.state) {
          setGameState(message.state);
        }
        if (message.room) {
          setRoom(message.room);
        }
        setIsPlaying(false);
        setStatusTitle(t("statusLoaded", language));
        setStatusText(
          gameState
            ? format(t("statusLoadedDetail", language), { day: gameState.day })
            : ""
        );
      }

      if (message.type === "error") {
        console.error("WebSocket error:", message.message);
        setIsPlaying(false);
        setStatusTitle(t("statusError", language));
        setStatusText(message.message);
      }
    };

    ws.onerror = () => {
      setIsPlaying(false);
      setStatusTitle(t("statusError", language));
      setStatusText(t("statusErrorDetail", language));
    };

    ws.onclose = () => {
      setIsPlaying(false);
    };
  }

  // 初始化时尝试从 URL 参数恢复房间
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const roomId = params.get("room");
      if (roomId && !room) {
        fetch(`/api/rooms/${roomId}`, { headers: { Accept: "application/json" } })
          .then((res) => {
            if (res.ok) return res.json();
            return null;
          })
          .then((data) => {
            if (data) {
              setRoom(data);
              setStatusTitle(t("roomReady", language));
              setStatusText(
                format(t("roomReadyDetail", language), {
                  roomId: truncate(data.id),
                  agentType: data.agent_type
                    ? data.agent_type === "llm"
                      ? t("agentLlm", language)
                      : t("agentHeuristic", language)
                    : t("agentHeuristic", language),
                })
              );
            }
          })
          .catch(() => {
            // 忽略错误
          });
      }
    }
  }, []);

  return (
    <div className="min-h-screen bg-background p-4 md:p-6 lg:p-8">
      {/* Hero Section */}
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col lg:flex-row gap-4 items-start lg:items-center justify-between mb-6">
          <div>
            <p className="text-sm font-medium text-primary">{t("brand", language)}</p>
            <h1 className="text-3xl font-bold text-textPrimary mt-1">
              {t("title", language)}
            </h1>
            <p className="text-textSecondary mt-1">{t("subtitle", language)}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default">
              {t("roomLabel", language)}: {room ? truncate(room.id) : "-"}
            </Badge>
            <Badge variant="default">
              {t("gameLabel", language)}: {gameState ? truncate(gameState.id) : "-"}
            </Badge>
            <Badge variant={viewMode === "moderator" ? "warning" : "default"}>
              {viewMode === "moderator" ? t("private", language) : t("publicMode", language)}
            </Badge>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-textSecondary">{t("winner", language)}</p>
              <p className="text-xl font-bold text-textPrimary mt-1">
                {gameState?.winner
                  ? gameState.winner === "village"
                    ? t("village", language)
                    : t("wolf", language)
                  : "-"}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-textSecondary">{t("day", language)}</p>
              <p className="text-xl font-bold text-textPrimary mt-1">
                {gameState?.day || "-"}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-textSecondary">{t("phase", language)}</p>
              <p className="text-xl font-bold text-textPrimary mt-1">
                {gameState?.phase ? tPhase(gameState.phase, language) : "-"}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <p className="text-sm text-textSecondary">{t("events", language)}</p>
              <p className="text-xl font-bold text-textPrimary mt-1">
                {gameState?.event_count || 0}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Controls & Status */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
          {/* Control Panel */}
          <Card>
            <CardHeader>
              <CardTitle>{t("controlPanel", language)}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {/* Language Switch */}
                <div className="flex items-center gap-2">
                  <span className="text-sm text-textSecondary flex-1">
                    {language === "zh" ? "中文" : "English"}
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant={language === "zh" ? "primary" : "ghost"}
                      size="sm"
                      onClick={() => setLanguage(Language.ZH)}
                    >
                      中文
                    </Button>
                    <Button
                      variant={language === "en" ? "primary" : "ghost"}
                      size="sm"
                      onClick={() => setLanguage(Language.EN)}
                    >
                      EN
                    </Button>
                  </div>
                </div>

                {/* Agent Type */}
                <div className="space-y-2">
                  <label className="text-sm text-textSecondary">{t("agentType", language)}</label>
                  <select
                    value={agentType}
                    onChange={(e) =>
                      setAgentType(e.target.value === "llm" ? AgentType.LLM : AgentType.HEURISTIC)
                    }
                    className="w-full h-10 px-3 rounded-button border border-border bg-cardBackground text-textPrimary"
                    disabled={isPlaying}
                  >
                    <option value="heuristic">{t("agentHeuristic", language)}</option>
                    <option value="llm">{t("agentLlm", language)}</option>
                  </select>
                </div>

                {/* Seed */}
                <div className="space-y-2">
                  <label className="text-sm text-textSecondary">{t("seed", language)}</label>
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(parseInt(e.target.value) || 7)}
                    className="w-full h-10 px-3 rounded-button border border-border bg-cardBackground text-textPrimary"
                    disabled={isPlaying}
                  />
                </div>

                {/* Speed */}
                <div className="space-y-2">
                  <label className="text-sm text-textSecondary">{t("speed", language)}</label>
                  <input
                    type="number"
                    value={speed}
                    onChange={(e) => setSpeed(parseInt(e.target.value) || 80)}
                    className="w-full h-10 px-3 rounded-button border border-border bg-cardBackground text-textPrimary"
                    disabled={isPlaying}
                  />
                </div>

                {/* Buttons */}
                <div className="flex flex-col gap-2 pt-2">
                  <Button onClick={runGame} disabled={isPlaying} className="w-full">
                    {isPlaying ? t("statusStreaming", language) : t("run", language)}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      setViewMode(
                        viewMode === ViewMode.MODERATOR ? ViewMode.PUBLIC : ViewMode.MODERATOR
                      )
                    }
                    disabled={isPlaying}
                    className="w-full"
                  >
                    {viewMode === ViewMode.MODERATOR
                      ? t("public", language)
                      : t("private", language)}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Status Panel */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>{t("runtimeStatus", language)}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div>
                  <p className="font-semibold text-textPrimary">{statusTitle}</p>
                  <p className="text-sm text-textSecondary mt-1">{statusText}</p>
                </div>

                {/* Latest Event */}
                {gameState?.last_event && (
                  <div className="border-t border-border pt-4">
                    <p className="text-sm font-medium text-textSecondary">
                      {t("latestEvent", language)}
                    </p>
                    <p className="font-medium text-textPrimary mt-1">
                      {gameState.last_event.type}
                    </p>
                    <p className="text-sm text-textSecondary mt-1">
                      {gameState.last_event.payload?.message ||
                        JSON.stringify(gameState.last_event.payload)}
                    </p>
                  </div>
                )}

                {/* Stats */}
                <div className="grid grid-cols-2 gap-4 pt-2 border-t border-border">
                  <div>
                    <span className="text-sm text-textSecondary">{t("aliveCount", language)}</span>
                    <p className="font-semibold text-textPrimary mt-1">
                      {gameState?.alive_count ||
                        gameState?.players.filter((p) => p.alive).length ||
                        "-"}
                    </p>
                  </div>
                  <div>
                    <span className="text-sm text-textSecondary">{t("agentMode", language)}</span>
                    <p className="font-semibold text-textPrimary mt-1">
                      {agentType === "llm" ? t("agentLlm", language) : t("agentHeuristic", language)}
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Players */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>{t("players", language)}</CardTitle>
              <span className="text-sm text-textSecondary">{t("boardHint", language)}</span>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {(gameState?.players || []).map((player) => (
                  <PlayerCard key={player.id} player={player} />
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Timeline */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>{t("timeline", language)}</CardTitle>
              <span className="text-sm text-textSecondary">{t("timelineHint", language)}</span>
            </CardHeader>
            <CardContent>
              <div className="max-h-[500px] overflow-y-auto">
                {gameState?.events.length ? (
                  [...gameState.events].reverse().map((event, index) => (
                    <EventItem key={event.id || index} event={event} />
                  ))
                ) : (
                  <div className="text-center py-8 text-textSecondary">
                    {t("statusHint", language)}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Notes */}
          <Card>
            <CardHeader>
              <CardTitle>{t("observerNotes", language)}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="border-l-2 border-primary pl-3">
                <p className="text-sm font-medium text-primary">{t("dailySummary", language)}</p>
                <div className="mt-2 space-y-1">
                  {gameState?.daily_summaries &&
                  gameState.daily_summaries[gameState.day]?.length ? (
                    gameState.daily_summaries[gameState.day]
                      .slice(-5)
                      .map((line, index) => (
                        <p key={index} className="text-sm text-textSecondary">
                          {line}
                        </p>
                      ))
                  ) : (
                    <p className="text-sm text-textSecondary">-</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-textPrimary">{t("roomLabel", language)}</p>
                <p className="text-sm text-textSecondary">{t("roomDescription", language)}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-textPrimary">{t("agentMode", language)}</p>
                <p className="text-sm text-textSecondary">{t("agentDescription", language)}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-textPrimary">{t("viewMode", language)}</p>
                <p className="text-sm text-textSecondary">{t("viewDescription", language)}</p>
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium text-textPrimary">{t("streamingLabel", language)}</p>
                <p className="text-sm text-textSecondary">{t("streamingDescription", language)}</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
