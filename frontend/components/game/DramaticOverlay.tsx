"use client";

import { useEffect, useRef, useState } from "react";
import { useAppContext } from "@/context/AppContext";
import { cn } from "@/lib/utils";

interface OverlayState {
  visible: boolean;
  title: string;
  subtitle: string;
  type: "death" | "peaceful" | "elimination" | null;
}

export function DramaticOverlay({ onVisibilityChange }: { onVisibilityChange?: (visible: boolean) => void }) {
  const { gameState, language, speed } = useAppContext();
  const [overlay, setOverlay] = useState<OverlayState>({ visible: false, title: "", subtitle: "", type: null });
  const lastEventIdRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevPhaseRef = useRef<string | undefined>(undefined);

  // Notify parent when overlay visibility changes (for animation coordination)
  useEffect(() => {
    onVisibilityChange?.(!!overlay.type);
  }, [overlay.type, onVisibilityChange]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  function dismiss() {
    if (timerRef.current) clearTimeout(timerRef.current);
    setOverlay((prev) => {
      if (!prev.type) return prev;
      return { ...prev, visible: false };
    });
    timerRef.current = setTimeout(() => {
      setOverlay({ visible: false, title: "", subtitle: "", type: null });
    }, 200);
  }

  // Dismiss when phase changes — the next PhaseAnnouncement is about to start
  useEffect(() => {
    const phase = gameState?.phase;
    if (phase && prevPhaseRef.current && phase !== prevPhaseRef.current) {
      dismiss();
    }
    prevPhaseRef.current = phase;
  }, [gameState?.phase]);

  useEffect(() => {
    if (!gameState?.events?.length) return;
    const lastEvent = gameState.events[gameState.events.length - 1];
    if (!lastEvent || lastEvent.id === lastEventIdRef.current) return;
    lastEventIdRef.current = lastEvent.id;

    if (lastEvent.type !== "SYSTEM_MESSAGE") return;
    const msg: string = (lastEvent.payload as any)?.message || "";

    let title = "";
    let subtitle = "";
    let type: OverlayState["type"] = null;

    if (msg.startsWith("Night deaths:")) {
      const names = msg.replace("Night deaths:", "").replace(/\./g, "").trim();
      title = language === "zh" ? "昨夜死亡" : "Last Night";
      subtitle = names || msg;
      type = "death";
    } else if (msg === "No one died last night.") {
      title = language === "zh" ? "昨夜平安夜" : "Peaceful Night";
      subtitle = language === "zh" ? "无人死亡" : "No one died";
      type = "peaceful";
    } else if (msg.includes("was voted out")) {
      const name = msg.replace("was voted out.", "").trim();
      title = language === "zh" ? "投票放逐" : "Voted Out";
      subtitle = name || msg;
      type = "elimination";
    } else if (msg.includes("revealed as Idiot")) {
      title = language === "zh" ? "白痴翻牌" : "Idiot Revealed";
      subtitle = msg;
      type = "death";
    }

    if (!type) return;

    // Display duration = speed minus fade time, so the overlay finishes
    // before the backend advances to the next phase. Floor at 400ms.
    const displayMs = Math.max(400, speed - 200);

    if (timerRef.current) clearTimeout(timerRef.current);
    setOverlay({ visible: true, title, subtitle, type });

    timerRef.current = setTimeout(() => {
      setOverlay((prev) => ({ ...prev, visible: false }));
      timerRef.current = setTimeout(() => {
        setOverlay({ visible: false, title: "", subtitle: "", type: null });
      }, 400);
    }, displayMs);
  }, [gameState?.events?.length, language, speed]);

  if (!overlay.type) return null;

  const bgMap: Record<string, string> = {
    death: "bg-gradient-to-b from-red-950/90 via-black/80 to-transparent",
    peaceful: "bg-gradient-to-b from-emerald-950/90 via-black/80 to-transparent",
    elimination: "bg-gradient-to-b from-amber-950/90 via-black/80 to-transparent",
  };

  const iconMap: Record<string, string> = {
    death: "☠",
    peaceful: "☽",
    elimination: "⚒",
  };

  return (
    <div
      role="alert"
      aria-live="assertive"
      className={cn(
        "fixed inset-0 z-[999] flex items-center justify-center pointer-events-none transition-opacity duration-300",
        bgMap[overlay.type],
        overlay.visible ? "opacity-100" : "opacity-0",
      )}
    >
      <div
        className={cn(
          "text-center transition-all duration-400",
          overlay.visible ? "scale-100 opacity-100" : "scale-110 opacity-0",
        )}
      >
        <div className="mb-3 font-display text-6xl leading-none text-white/80 drop-shadow-lg">
          {iconMap[overlay.type]}
        </div>
        <h2 className="font-display text-3xl font-bold text-white drop-shadow-lg mb-2">
          {overlay.title}
        </h2>
        <p className="text-xl text-white/70 font-medium tracking-wider">
          {overlay.subtitle}
        </p>
      </div>
    </div>
  );
}
