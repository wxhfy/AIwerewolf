"use client";

import { useEffect, useRef } from "react";
import { tRole } from "@/lib/i18n";
import type { Language } from "@/types";

interface RoleRevealOverlayProps {
  role: string;
  alignment: string;
  seat: number;
  name: string;
  wolfTeammates: string[];
  language: Language;
  onRevealed: () => void;
}

export function RoleRevealOverlay({
  role, alignment, seat, name, wolfTeammates, language, onRevealed,
}: RoleRevealOverlayProps) {
  const onRevealedRef = useRef(onRevealed);

  useEffect(() => {
    onRevealedRef.current = onRevealed;
  }, [onRevealed]);

  useEffect(() => {
    const t = setTimeout(() => onRevealedRef.current(), 3000);
    return () => clearTimeout(t);
  }, []);

  return (
    <div data-testid="role-reveal-overlay" className="fixed top-20 left-1/2 -translate-x-1/2 z-[200] pointer-events-none">
      <div className="animate-slide-in rounded-xl bg-cardBackground/95 backdrop-blur border border-primary/30 shadow-xl px-6 py-4 text-center">
        <p className={`text-xl font-bold ${alignment === "wolf" ? "text-danger" : "text-success"}`}>
          {tRole(role, language)}
        </p>
        <p className="text-sm text-text-sub mt-1">
          {seat}号 {name}
        </p>
        {wolfTeammates.length > 0 && (
          <p className="text-xs text-danger/70 mt-1">
            {language === "zh" ? "狼队友" : "Wolf"}：{wolfTeammates.join(" · ")}
          </p>
        )}
        <p className="text-[10px] text-text-sub/30 mt-2 animate-pulse">
          {language === "zh" ? "即将进入游戏..." : "Entering game..."}
        </p>
      </div>
    </div>
  );
}
