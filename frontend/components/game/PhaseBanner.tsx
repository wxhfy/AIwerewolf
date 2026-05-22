"use client";

import React from "react";
import { useAppContext } from "@/context/AppContext";
import { tPhase } from "@/lib/i18n";
import { Badge } from "@/components/ui/Badge";
import { Language } from "@/types";

interface PhaseBannerProps {
  day: number;
  phase: string;
  isNight: boolean;
}

export function PhaseBanner({ day, phase, isNight }: PhaseBannerProps) {
  const { language } = useAppContext();

  return (
    <div className="flex items-center justify-center gap-3 py-4">
      <div className="flex items-center gap-2">
        <span className="text-2xl" aria-hidden="true">
          {isNight ? "☽" : "☀"}
        </span>
        <span className="font-display text-xl text-textPrimary">
          {formatDayLabel(day, phase, isNight, language)}
        </span>
      </div>
      <Badge variant={isNight ? "default" : "phase"}>
        {tPhase(phase, language)}
      </Badge>
    </div>
  );
}

function formatDayLabel(
  day: number,
  phase: string,
  isNight: boolean,
  lang: Language
): string {
  const phaseLabel = tPhase(phase, lang);
  const prefix = lang === "zh" ? `第${day}天` : `Day ${day}`;
  return `${prefix} · ${phaseLabel}`;
}
