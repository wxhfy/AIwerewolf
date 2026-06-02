"use client";

import { useAppContext } from "@/context/AppContext";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export interface PhaseAnnouncementProps {
  group: "ready" | "day" | "night" | "end";
  visible: boolean;
}

const announcementMeta = {
  ready: { icon: "◇", key: "phaseAnnouncementReady", className: "phase-announcement-ready" },
  night: { icon: "◐", key: "phaseAnnouncementNight", className: "phase-announcement-night" },
  day: { icon: "☼", key: "phaseAnnouncementDay", className: "phase-announcement-day" },
  end: { icon: "✦", key: "phaseAnnouncementEnd", className: "phase-announcement-end" },
} as const;

export function PhaseAnnouncement({ group, visible }: PhaseAnnouncementProps) {
  const { language } = useAppContext();
  const meta = announcementMeta[group];
  const text = t(meta.key, language);

  return (
    <div
      data-testid="phase-announcement"
      aria-label={text}
      aria-live="polite"
      className={cn(
        "fixed inset-0 z-[1000] flex items-center justify-center pointer-events-none transition-opacity duration-400 motion-reduce:transition-none",
        meta.className,
        visible ? "opacity-100" : "opacity-0",
      )}
    >
      <div className={`text-center transition-all duration-500 motion-reduce:transition-none ${visible ? "scale-100 opacity-100" : "scale-125 opacity-0"}`}>
        <div className="mb-4 font-display text-7xl leading-none tracking-[0.18em] text-primary drop-shadow-lg">{meta.icon}</div>
        <h1 className="font-display text-5xl font-bold text-textPrimary drop-shadow-lg">
          {text}
        </h1>
      </div>
    </div>
  );
}
