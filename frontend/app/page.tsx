"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { Language, AgentType } from "@/types";
import { Button } from "@/components/ui/Button";

export default function LobbyPage() {
  const router = useRouter();
  const { language, setLanguage, agentType, setAgentType, setGameState } = useAppContext();

  // Force LLM as the only public agent type. The user wants every game to be
  // LLM-driven; the heuristic agent stays in the codebase but only as the
  // automatic fallback inside LLMAgent (triggered after 3 LLM retries fail).
  useEffect(() => {
    if (agentType !== "llm") setAgentType("llm" as AgentType);
  }, [agentType, setAgentType]);

  const [playerCount, setPlayerCount] = useState(7);
  const [mode, setMode] = useState<"ai" | "human">("ai");
  const [humanSeat, setHumanSeat] = useState(1);
  const [seed, setSeed] = useState(Math.floor(Math.random() * 1000));
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [createdRoom, setCreatedRoom] = useState<any>(null);
  const [isStarting, setIsStarting] = useState(false);

  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  // Step 1: Create room → show modal
  async function handleCreateRoom() {
    setIsCreating(true);
    setError("");
    try {
      const params = new URLSearchParams({
        name: "Demo Room",
        seed: String(seed),
        player_count: String(playerCount),
        agent_type: agentType,
      });
      if (mode === "human") params.set("human_seat", String(humanSeat));
      const res = await fetch(`/api/rooms?${params.toString()}`, { method: "POST" });
      if (!res.ok) throw new Error(`Failed to create room (${res.status})`);
      const room = await res.json();
      setCreatedRoom(room);
      setShowModal(true);
    } catch (e: any) {
      setError(e.message || "创建房间失败");
    } finally {
      setIsCreating(false);
    }
  }

  // Step 2: Confirm → for human mode call /start (needs first human turn ready);
  // for AI-vs-AI call /prepare so the play page lands with all seats / roles /
  // personas already filled in. The play page then opens a WebSocket which
  // takes over driving the game (stream_game detects the prepared active_game
  // and calls game.play() itself — no second build, no parallel run).
  async function handleConfirmStart() {
    setIsStarting(true);
    setError("");
    try {
      if (mode === "human") {
        const res = await fetch(`/api/rooms/${createdRoom.id}/start?show_private=true`, { method: "POST" });
        if (!res.ok) throw new Error(`Start failed (${res.status})`);
        const snapshot = await res.json();
        setGameState(snapshot);
      } else {
        const res = await fetch(`/api/rooms/${createdRoom.id}/prepare?show_private=true`, { method: "POST" });
        if (!res.ok) throw new Error(`Prepare failed (${res.status})`);
        const snapshot = await res.json();
        setGameState(snapshot);
      }
      router.push(`/room/${createdRoom.id}/play?human_seat=${humanSeat}&mode=${mode}`);
    } catch (e: any) {
      setError(e.message || "启动失败");
      setIsStarting(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: "var(--color-bg)", transition: "background var(--transition-daynight) var(--ease-in-out)" }}>
      {/* Language toggle */}
      <div className="absolute top-4 right-4 flex rounded-button border overflow-hidden"
        style={{ borderColor: "var(--color-border)" }}>
        <button onClick={() => setLanguage(Language.ZH)}
          className={`px-3 py-1.5 text-xs font-medium ${language === "zh" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>中文</button>
        <button onClick={() => setLanguage(Language.EN)}
          className={`px-3 py-1.5 text-xs font-medium ${language === "en" ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>EN</button>
      </div>

      {/* Brand */}
      <div className="text-center mb-10">
        <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1"
          strokeLinecap="round" strokeLinejoin="round" className="mx-auto mb-4 text-primary">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
        <h1 className="font-display text-3xl font-bold text-primary">AI Werewolf</h1>
        <p className="mt-2 text-text-sub text-sm max-w-xs mx-auto">
          {t("配置游戏参数，开始一局 AI 狼人杀对战", "Configure your game and start an AI Werewolf match")}
        </p>
      </div>

      {/* Config Card */}
      <div className="w-full max-w-md rounded-card p-6 space-y-5"
        style={{ background: "var(--color-card)", border: "1px solid var(--color-border)", boxShadow: "0 4px 24px rgba(0,0,0,0.05)" }}>
        {/* Mode */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">{t("游戏模式", "Game Mode")}</label>
          <div className="flex rounded-button border overflow-hidden" style={{ borderColor: "var(--color-border)" }}>
            {(["ai", "human"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`flex-1 py-2 text-sm font-medium ${mode === m ? "bg-primary text-white" : "bg-transparent text-text-sub"}`}>
                {m === "ai" ? t("AI 对战", "AI vs AI") : t("真人参与", "Human Play")}
              </button>
            ))}
          </div>
        </div>

        {/* Player count */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">{t("玩家数量", "Player Count")}</label>
          <select value={playerCount} onChange={(e) => { const n = Number(e.target.value); setPlayerCount(n); if (humanSeat > n) setHumanSeat(n); }}
            className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
            style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }}>
            {[7, 8, 9, 10, 11, 12].map((n) => <option key={n} value={n}>{n} {t("人", " players")}</option>)}
          </select>
        </div>

        {/* Human seat */}
        {mode === "human" && (
          <div>
            <label className="block text-sm font-medium text-textPrimary mb-2">{t("你的座位号", "Your Seat")}</label>
            <select value={humanSeat} onChange={(e) => setHumanSeat(Number(e.target.value))}
              className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
              style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }}>
              {Array.from({ length: playerCount }, (_, i) => i + 1).map((s) => <option key={s} value={s}>{t("座位", "Seat")} {s}</option>)}
            </select>
          </div>
        )}

        {/* Agent type — fixed to LLM. The toggle was confusing because the
            heuristic option was meant as the in-LLM fallback, not a top-level
            choice. We keep AgentType in the context (still used by the play
            page when opening the WebSocket) but force it to "llm". */}

        {/* Seed */}
        <div>
          <label className="block text-sm font-medium text-textPrimary mb-2">Seed</label>
          <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)}
            className="w-full h-10 px-3 rounded-button border text-sm text-textPrimary"
            style={{ background: "var(--color-bg)", borderColor: "var(--color-border)" }} />
        </div>

        {error && <p className="text-sm text-danger text-center">{error}</p>}

        <Button onClick={handleCreateRoom} disabled={isCreating} className="w-full h-11 text-base">
          {isCreating ? t("创建中...", "Creating...") : t("开始游戏", "Start Game")}
        </Button>
      </div>

      <p className="mt-8 text-xs text-text-sub">
        <span className="font-display">AI Werewolf</span><span className="mx-2">·</span>
        <span>{t("观战 & 对战", "Spectate & Play")}</span>
      </p>

      {/* ====== Preparation Modal ====== */}
      {showModal && createdRoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.45)", backdropFilter: "blur(2px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowModal(false); }}>
          <div className="w-full max-w-sm rounded-card p-6 space-y-5 animate-scale-in"
            style={{ background: "var(--color-card)", border: "1px solid var(--color-border)", boxShadow: "0 16px 48px rgba(0,0,0,0.12)" }}
            onClick={(e) => e.stopPropagation()}>
            <div className="text-center">
              <h2 className="font-display text-xl font-bold text-primary">{t("准备开始", "Ready to Start")}</h2>
              <p className="mt-1 text-sm text-text-sub">{t("确认以下设置后开始游戏", "Confirm settings to start")}</p>
            </div>

            {/* Room info */}
            <div className="space-y-2 text-sm">
              {[
                [t("房间", "Room"), createdRoom.id.slice(0, 8) + "..."],
                [t("模式", "Mode"), mode === "human" ? t("真人参与", "Human Play") : t("AI 对战", "AI vs AI")],
                [t("人数", "Players"), String(playerCount)],
                [t("AI 类型", "Agent"), agentType === "heuristic" ? t("启发式", "Heuristic") : "LLM"],
                ...(mode === "human" ? [[t("你的座位", "Your Seat"), `${t("座位", "Seat")} ${humanSeat}`]] as any : []),
              ].map(([label, value]: any) => (
                <div key={label} className="flex justify-between py-1.5 border-b" style={{ borderColor: "var(--color-border)" }}>
                  <span className="text-text-sub">{label}</span>
                  <span className="font-medium text-textPrimary">{value}</span>
                </div>
              ))}
            </div>

            {/* Seat preview */}
            <div>
              <p className="text-sm font-medium text-textPrimary mb-2">{t("座位分布", "Seat Layout")}</p>
              <div className="grid grid-cols-4 gap-1.5">
                {Array.from({ length: playerCount }, (_, i) => i + 1).map((s) => (
                  <div key={s} className="flex flex-col items-center p-2 rounded-lg border text-xs"
                    style={{ borderColor: s === humanSeat && mode === "human" ? "var(--color-primary)" : "var(--color-border)", background: s === humanSeat && mode === "human" ? "rgba(139,90,43,0.08)" : "var(--color-bg)" }}>
                    <span className="font-medium text-textPrimary">{s}</span>
                    <span className="text-text-sub mt-0.5">{mode === "human" && s === humanSeat ? t("你", "YOU") : "AI"}</span>
                  </div>
                ))}
              </div>
            </div>

            {error && <p className="text-sm text-danger text-center">{error}</p>}

            <div className="flex gap-3 pt-1">
              <Button variant="ghost" onClick={() => { setShowModal(false); setError(""); }} className="flex-1">
                {t("取消", "Cancel")}
              </Button>
              <Button onClick={handleConfirmStart} disabled={isStarting} className="flex-1">
                {isStarting ? t("启动中...", "Starting...") : t("确认开始", "Confirm & Start")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
