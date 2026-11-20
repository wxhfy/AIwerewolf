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
    <div data-testid="role-reveal-overlay" role="status" aria-live="polite" className="pointer-events-none fixed inset-x-3 top-20 z-[200] mx-auto max-w-sm">
      <div className="rounded-card border border-primary/30 bg-cardBackground px-5 py-5 text-center shadow-modal animate-slide-in">
        <p className="mb-2 text-xs tracking-widest text-text-sub">{language === "zh" ? "你的身份" : "Your identity"}</p>
        <p className={`font-display text-2xl font-bold ${alignment === "wolf" ? "text-danger" : "text-success"}`}>
          {tRole(role, language)}
        </p>
        <p className="mt-1 break-words text-sm text-textPrimary">
          {language === "zh" ? `${seat}号` : `#${seat}`} · {name}
        </p>
        {wolfTeammates.length > 0 && (
          <p className="mt-3 rounded-button bg-danger/10 px-3 py-2 text-xs leading-relaxed text-danger">
            {language === "zh" ? "狼队友" : "Wolf teammates"}：{wolfTeammates.join(" · ")}
          </p>
        )}
        <p className="mt-3 border-t border-border pt-3 text-xs text-text-sub">
          {language === "zh" ? "请记住你的身份，即将进入游戏" : "Remember your role. The game is about to begin."}
        </p>
      </div>
    </div>
  );
}
