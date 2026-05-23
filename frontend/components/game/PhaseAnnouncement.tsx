"use client";

import React, { useEffect, useState } from "react";

interface PhaseAnnouncementProps {
  phase: string;
  prevPhase: string;
  onDone: () => void;
}

/** Map phase enum to announcement text and icon */
function phaseAnnounce(phase: string, prev: string): { icon: string; text: string; isNight: boolean } | null {
  const isNight = phase.startsWith("NIGHT");
  const isDay = phase.startsWith("DAY");
  const wasNight = prev.startsWith("NIGHT");

  // Night falls
  if (isNight && !wasNight) {
    return { icon: "\u{1F319}", text: "天黑请闭眼", isNight: true };
  }
  // Day breaks
  if (isDay && wasNight) {
    return { icon: "\u{2600}️", text: "天亮了", isNight: false };
  }
  // Specific actions
  if (phase === "DAY_VOTE") return { icon: "\u{1F5F3}️", text: "投票放逐", isNight: false };
  if (phase === "HUNTER_SHOOT") return { icon: "\u{1F3F9}", text: "猎人开枪", isNight: false };
  if (phase === "WHITE_WOLF_KING_BOOM") return { icon: "\u{1F4A5}", text: "白狼王爆炸", isNight: true };
  if (phase === "GAME_END") return { icon: "\u{1F3C6}", text: "游戏结束", isNight: false };

  // Generic night/day phase — no announcement needed
  return null;
}

export function PhaseAnnouncement({ phase, prevPhase, onDone }: PhaseAnnouncementProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const ann = phaseAnnounce(phase, prevPhase);
    if (!ann) { onDone(); return; }
    setVisible(true);
    const timer = setTimeout(() => { setVisible(false); onDone(); }, 2000);
    return () => clearTimeout(timer);
  }, [phase, prevPhase]);

  const ann = phaseAnnounce(phase, prevPhase);
  if (!ann) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center pointer-events-none transition-opacity duration-500"
      style={{
        background: ann.isNight
          ? "radial-gradient(ellipse at center, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.85) 100%)"
          : "radial-gradient(ellipse at center, rgba(255,255,255,0.6) 0%, rgba(255,248,240,0.85) 100%)",
        opacity: visible ? 1 : 0,
      }}
    >
      <div className={`text-center transition-all duration-700 ${visible ? "scale-100 opacity-100" : "scale-150 opacity-0"}`}>
        <div className="text-7xl mb-4 drop-shadow-lg">{ann.icon}</div>
        <h1 className={`font-display text-5xl font-bold drop-shadow-lg ${ann.isNight ? "text-[#EDE8E0]" : "text-[#2D2A24]"}`}>
          {ann.text}
        </h1>
      </div>
    </div>
  );
}
