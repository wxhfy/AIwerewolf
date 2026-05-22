"use client";

import React from "react";
import { useAppContext } from "@/context/AppContext";
import { t, tPhase } from "@/lib/i18n";
import { Badge } from "@/components/ui/Badge";
import { Language } from "@/types";

interface PhaseBannerProps {
  day: number;
  phase: string;
  isNight: boolean;
}

function SunIcon() {
  return (
    <svg
      width="28" height="28" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className="text-accent"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="5" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      width="28" height="28" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinecap="round" strokeLinejoin="round"
      className="text-primary"
      aria-hidden="true"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

export function PhaseBanner({ day, phase, isNight }: PhaseBannerProps) {
  const { language } = useAppContext();

  const isSetup = day === 0;
  const icon = isNight ? <MoonIcon /> : <SunIcon />;

  return (
    <div className="flex items-center justify-center gap-4 py-5">
      <div className="flex items-center gap-3">
        {/* Animated icon container */}
        <div
          className={`
            flex items-center justify-center w-11 h-11 rounded-full
            transition-all duration-800
            ${isNight
              ? "bg-primary/10 shadow-[0_0_16px_rgba(139,90,43,0.15)]"
              : "bg-accent/10 shadow-[0_0_16px_rgba(212,175,55,0.15)]"
            }
          `}
        >
          {icon}
        </div>

        {/* Day/Phase text */}
        <div className="flex flex-col">
          {isSetup ? (
            <span className="font-display text-xl text-textPrimary leading-tight">
              {t("statusReady", language)}
            </span>
          ) : (
            <>
              <span className="font-display text-xl text-textPrimary leading-tight">
                {language === "zh" ? `第${day}天` : `Day ${day}`}
              </span>
              <span className="text-sm text-text-sub leading-tight mt-0.5">
                {tPhase(phase, language)}
              </span>
            </>
          )}
        </div>
      </div>

      {!isSetup && (
        <Badge variant={isNight ? "default" : "phase"}>
          {isNight ? t("night", language) : t("dayLabel", language)}
        </Badge>
      )}
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
