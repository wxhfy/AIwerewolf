"use client";

import { useEffect } from "react";
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
  useEffect(() => {
    const t = setTimeout(() => onRevealed(), 3000);
    return () => clearTimeout(t);
  }, [onRevealed]);

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="text-center animate-scale-in">
        <p className="text-5xl mb-4">
          {alignment === "wolf" ? "🐺" : "🏘️"}
        </p>
        <p className={`text-3xl font-bold ${alignment === "wolf" ? "text-danger" : "text-success"}`}>
          {tRole(role, language)}
        </p>
        <p className="text-sm text-text-sub mt-1">
          {seat}号 {name}
        </p>
        {wolfTeammates.length > 0 && (
          <p className="text-xs text-danger/70 mt-2">
            {language === "zh" ? "狼队友" : "Wolf teammates"}：{wolfTeammates.join(" · ")}
          </p>
        )}
        <p className="text-[10px] text-text-sub/30 mt-4 animate-pulse">
          {language === "zh" ? "即将进入游戏..." : "Entering game..."}
        </p>
      </div>
    </div>
  );
}
