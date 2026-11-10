"use client";

import { useAppContext } from "@/context/AppContext";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export interface PhaseAnnouncementProps {
  group: "ready" | "day" | "night" | "end";
  visible: boolean;
  text?: string;
}

const keyMap: Record<string, string> = {
  ready: "phaseAnnouncementReady",
  night: "phaseAnnouncementNight",
  day: "phaseAnnouncementDay",
  end: "phaseAnnouncementEnd",
};

/** Plaque styling for each phase scenario: carved wood / brass / moonlight finish */
const plaqueStyles: Record<string, {
  border: string;
  bg: string;
  glow: string;
  text: string;
  subtext: string;
  icon: string;
  rivet: string;
}> = {
  ready: {
    border: "border-amber-700/60",
    bg: "bg-gradient-to-b from-[#2c1a0e] via-[#1c1008] to-[#120904]",
    glow: "shadow-[0_25px_60px_rgba(0,0,0,0.9),inset_0_1px_2px_rgba(255,220,150,0.25)]",
    text: "text-[#fae8c8]",
    subtext: "text-amber-300/70",
    icon: "📜",
    rivet: "bg-amber-600/70 border-amber-300/50",
  },
  day: {
    border: "border-amber-600/70",
    bg: "bg-gradient-to-b from-[#351e11] via-[#221208] to-[#140a04]",
    glow: "shadow-[0_25px_60px_rgba(0,0,0,0.92),inset_0_1px_2px_rgba(255,220,150,0.35)]",
    text: "text-[#fff1d6]",
    subtext: "text-amber-300/80",
    icon: "☀️",
    rivet: "bg-amber-500/80 border-amber-200/60",
  },
  night: {
    border: "border-indigo-400/60",
    bg: "bg-gradient-to-b from-[#141c2c] via-[#0d131f] to-[#070a12]",
    glow: "shadow-[0_25px_60px_rgba(0,0,0,0.96),inset_0_1px_2px_rgba(180,210,255,0.3)]",
    text: "text-[#e0e7ff]",
    subtext: "text-indigo-300/80",
    icon: "🌙",
    rivet: "bg-indigo-400/80 border-indigo-200/60",
  },
  end: {
    border: "border-amber-500/70",
    bg: "bg-gradient-to-b from-[#2e1313] via-[#1c0a0a] to-[#0c0404]",
    glow: "shadow-[0_25px_60px_rgba(0,0,0,0.95),inset_0_1px_2px_rgba(255,200,140,0.25)]",
    text: "text-[#fed7aa]",
    subtext: "text-rose-300/80",
    icon: "✦",
    rivet: "bg-amber-600/80 border-amber-300/60",
  },
};

export function PhaseAnnouncement({ group, visible, text: customText }: PhaseAnnouncementProps) {
  const { language } = useAppContext();
  const text = customText || t(keyMap[group] as any, language);
  const style = plaqueStyles[group] || plaqueStyles.ready;

  const hasDot = typeof text === "string" && text.includes(" · ");
  let eyebrow: string | null = null;
  let phrase = text;
  if (hasDot) {
    const parts = text.split(" · ");
    eyebrow = parts[0];
    phrase = parts.slice(1).join(" · ");
  }

  return (
    <div
      data-testid="phase-announcement"
      aria-label={text}
      aria-live="polite"
      className={cn(
        "fixed inset-0 z-[1000] flex items-center justify-center pointer-events-none transition-all duration-500 motion-reduce:transition-none px-4",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      {/* Carved Wood / Brass Plaque */}
      <div
        className={cn(
          "relative min-w-[280px] sm:min-w-[360px] max-w-lg rounded-2xl border-2 px-8 py-6 text-center transition-all duration-500 motion-reduce:transition-none",
          style.border,
          style.bg,
          style.glow,
          visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
        )}
      >
        {/* Brass corner rivets */}
        <span className={cn("absolute top-2.5 left-2.5 h-1.5 w-1.5 rounded-full border", style.rivet)} />
        <span className={cn("absolute top-2.5 right-2.5 h-1.5 w-1.5 rounded-full border", style.rivet)} />
        <span className={cn("absolute bottom-2.5 left-2.5 h-1.5 w-1.5 rounded-full border", style.rivet)} />
        <span className={cn("absolute bottom-2.5 right-2.5 h-1.5 w-1.5 rounded-full border", style.rivet)} />

        {/* Small emblem / icon */}
        {style.icon && (
          <div className="text-2xl sm:text-3xl mb-2 drop-shadow-md select-none">{style.icon}</div>
        )}

        {/* Top line for '第 N 夜/天' when split by ' · ' */}
        {hasDot && eyebrow && (
          <p
            className={cn(
              "font-display text-xs sm:text-sm font-semibold tracking-wider mb-1 select-none drop-shadow",
              style.subtext,
            )}
          >
            {eyebrow}
          </p>
        )}

        {/* Engraved plaque title text - tightened letter-spacing, nowrap when split */}
        <h1
          className={cn(
            "font-display text-2xl sm:text-4xl md:text-5xl font-bold tracking-normal sm:tracking-wide drop-shadow-[0_2px_6px_rgba(0,0,0,0.9)] select-none",
            hasDot ? "whitespace-nowrap" : "break-words",
            style.text,
          )}
        >
          {phrase}
        </h1>
      </div>
    </div>
  );
}
