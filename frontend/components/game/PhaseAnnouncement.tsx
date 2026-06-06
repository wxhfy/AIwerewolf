"use client";

import { useAppContext } from "@/context/AppContext";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export interface PhaseAnnouncementProps {
  group: "ready" | "day" | "night" | "end";
  visible: boolean;
}

const keyMap: Record<string, string> = {
  ready: "phaseAnnouncementReady",
  night: "phaseAnnouncementNight",
  day: "phaseAnnouncementDay",
  end: "phaseAnnouncementEnd",
};

/** 不同场景的视觉风格：颜色 / 光晕 / 图标 */
const styleMap: Record<string, { text: string; glow: string; icon: string }> = {
  ready: { text: "text-textPrimary", glow: "shadow-white/10", icon: "" },
  night: { text: "text-indigo-200", glow: "shadow-indigo-500/30", icon: "🌙" },
  day:   { text: "text-amber-100", glow: "shadow-amber-400/30", icon: "☀️" },
  end:   { text: "text-rose-200", glow: "shadow-rose-500/30", icon: "✦" },
};

export function PhaseAnnouncement({ group, visible }: PhaseAnnouncementProps) {
  const { language } = useAppContext();
  const text = t(keyMap[group] as any, language);
  const style = styleMap[group];

  return (
    <div
      data-testid="phase-announcement"
      aria-label={text}
      aria-live="polite"
      className={cn(
        "fixed inset-0 z-[1000] flex items-center justify-center pointer-events-none transition-all duration-700 motion-reduce:transition-none",
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <div className={cn(
        "text-center transition-all duration-700 motion-reduce:transition-none",
        visible ? "scale-100 opacity-100" : "scale-110 opacity-0",
      )}>
        {style.icon && (
          <div className="text-4xl mb-3 drop-shadow-lg">{style.icon}</div>
        )}
        <h1 className={cn(
          "font-display text-5xl font-bold tracking-wider drop-shadow-lg",
          style.text, style.glow,
        )}>
          {text}
        </h1>
      </div>
    </div>
  );
}
