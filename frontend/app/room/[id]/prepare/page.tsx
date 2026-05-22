"use client";

import React, { useState, useEffect } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { useAppContext } from "@/context/AppContext";
import { Button } from "@/components/ui/Button";

export default function PreparePage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { language, room, setRoom, setGameState } = useAppContext();

  const roomId = params.id;
  const mode = searchParams.get("mode") || "ai";
  const humanSeat = Number(searchParams.get("human_seat") || 1);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [roomData, setRoomData] = useState<any>(room);

  useEffect(() => {
    if (!roomData || roomData.id !== roomId) {
      fetch(`/api/rooms/${roomId}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (d) { setRoomData(d); setRoom(d); } })
        .catch(() => setError("无法加载房间信息"));
    }
  }, [roomId]);

  async function handleConfirmStart() {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/rooms/${roomId}/start?show_private=true`, { method: "POST" });
      if (!res.ok) throw new Error(`Start failed (${res.status})`);
      const snapshot = await res.json();
      setGameState(snapshot);
      router.push(`/room/${roomId}/play?human_seat=${humanSeat}&mode=${mode}`);
    } catch (e: any) {
      setError(e.message || "启动失败");
      setLoading(false);
    }
  }

  const t = (zh: string, en: string) => (language === "zh" ? zh : en);
  const pc = roomData?.player_count || 7;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: "var(--color-bg)", transition: "background var(--transition-daynight) var(--ease-in-out)" }}>
      <div className="w-full max-w-md rounded-card p-6 space-y-5"
        style={{ background: "var(--color-card)", border: "1px solid var(--color-border)", boxShadow: "0 4px 24px rgba(0,0,0,0.04)" }}>
        <div className="text-center">
          <h1 className="font-display text-2xl font-bold text-primary">
            {t("准备开始", "Ready to Start")}
          </h1>
          <p className="mt-2 text-sm text-text-sub">
            {t("确认以下设置后开始游戏", "Confirm settings below to start the game")}
          </p>
        </div>

        {/* Room info */}
        <div className="space-y-2 text-sm">
          <div className="flex justify-between py-1.5 border-b" style={{ borderColor: "var(--color-border)" }}>
            <span className="text-text-sub">{t("房间", "Room")}</span>
            <span className="font-medium text-textPrimary font-mono text-xs">{roomId.slice(0, 8)}...</span>
          </div>
          <div className="flex justify-between py-1.5 border-b" style={{ borderColor: "var(--color-border)" }}>
            <span className="text-text-sub">{t("模式", "Mode")}</span>
            <span className="font-medium text-textPrimary">{mode === "human" ? t("真人参与", "Human Play") : t("AI 对战", "AI vs AI")}</span>
          </div>
          <div className="flex justify-between py-1.5 border-b" style={{ borderColor: "var(--color-border)" }}>
            <span className="text-text-sub">{t("人数", "Players")}</span>
            <span className="font-medium text-textPrimary">{pc}</span>
          </div>
          {mode === "human" && (
            <div className="flex justify-between py-1.5 border-b" style={{ borderColor: "var(--color-border)" }}>
              <span className="text-text-sub">{t("你的座位", "Your Seat")}</span>
              <span className="font-medium text-textPrimary">{t("座位", "Seat")} {humanSeat}</span>
            </div>
          )}
        </div>

        {/* Seat preview */}
        <div>
          <p className="text-sm font-medium text-textPrimary mb-3">
            {t("座位分布", "Seat Layout")}
          </p>
          <div className="grid grid-cols-4 gap-2">
            {Array.from({ length: pc }, (_, i) => i + 1).map((seat) => (
              <div key={seat}
                className="flex flex-col items-center p-2 rounded-lg border text-xs transition-all"
                style={{
                  borderColor: seat === humanSeat && mode === "human" ? "var(--color-primary)" : "var(--color-border)",
                  background: seat === humanSeat && mode === "human" ? "rgba(139,90,43,0.08)" : "var(--color-bg)",
                }}>
                <span className="font-medium text-textPrimary">{t("座位", "")}{seat}</span>
                <span className="text-text-sub mt-0.5">
                  {mode === "human" && seat === humanSeat ? t("你", "YOU") : "AI"}
                </span>
              </div>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-danger text-center">{error}</p>}

        <div className="flex gap-3 pt-2">
          <Button variant="ghost" onClick={() => router.push("/")} className="flex-1">
            {t("返回", "Back")}
          </Button>
          <Button onClick={handleConfirmStart} disabled={loading} className="flex-1">
            {loading ? t("启动中...", "Starting...") : t("确认开始", "Confirm & Start")}
          </Button>
        </div>
      </div>
    </div>
  );
}
