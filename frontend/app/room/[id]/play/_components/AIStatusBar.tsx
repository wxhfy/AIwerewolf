"use client";

import { t } from "@/lib/i18n";
import { deriveStatusText } from "@/lib/deriveStatusText";
import { Language, type GameState } from "@/types";
import type { useGameDerivedState } from "@/hooks/useGameDerivedState";

interface AIStatusBarProps {
  gameState: GameState | null;
  derived: ReturnType<typeof useGameDerivedState>;
  language: Language;
}

function formatActor(actor: { seat?: number; name?: string } | undefined, language: Language): string {
  if (!actor) return "";
  if (!actor.seat) return actor.name || (language === Language.ZH ? "行动中" : "acting");
  return language === Language.ZH
    ? `${actor.seat}号 ${actor.name || ""}`.trim()
    : `#${actor.seat} ${actor.name || ""}`.trim();
}

export function AIStatusBar({ gameState, derived, language }: AIStatusBarProps) {
  const { statusTitle, actionText } = deriveStatusText(gameState, language, derived.speakerState);
  const progress = gameState?.runtime_progress;
  const current = progress?.current?.[0];
  const queue = progress?.queue || [];
  const remaining = Number(progress?.remaining_count ?? queue.length);
  const eta = progress?.estimated_wait_seconds;
  const thinkingLabel = current
    ? (language === Language.ZH
        ? `${formatActor(current, language)} 思考中`
        : `${formatActor(current, language)} thinking`)
    : "";
  const queueLabel = remaining > 0
    ? (language === Language.ZH ? `队列剩余 ${remaining}` : `${remaining} left in queue`)
    : (progress?.simultaneous && (progress.thinking_count || 0) > 1
        ? (language === Language.ZH
            ? `${progress.thinking_count} 人并行思考`
            : `${progress.thinking_count} thinking in parallel`)
        : "");
  const etaLabel = typeof eta === "number" && eta > 0
    ? (language === Language.ZH ? `约 ${Math.ceil(eta)}s` : `~${Math.ceil(eta)}s`)
    : "";

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-cardBackground px-5 py-2.5 text-base font-medium">
      <span className="font-semibold text-textPrimary">{statusTitle}</span>
      {actionText && (
        <span className="text-text-sub">
          · <span className="text-primary font-medium">{actionText}</span>
        </span>
      )}
      {thinkingLabel && (
        <span data-testid="runtime-progress-current" className="text-primary/90 text-sm font-medium">
          · {thinkingLabel}
          <span className="inline-flex ml-0.5 text-primary/60">
            <span className="animate-dot-1">.</span>
            <span className="animate-dot-2">.</span>
            <span className="animate-dot-3">.</span>
          </span>
        </span>
      )}
      {queueLabel && (
        <span data-testid="runtime-progress-queue" className="text-text-sub text-sm">
          · {queueLabel}
          {queue.length > 0 && (
            <span className="text-text-sub/70">
              {" "}({queue.slice(0, 3).map((p) => (language === Language.ZH ? `${p.seat}号` : `#${p.seat}`)).join("、")}
              {queue.length > 3 ? (language === Language.ZH ? "…" : "…") : ""})
            </span>
          )}
        </span>
      )}
      {etaLabel && (
        <span data-testid="runtime-progress-eta" className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
          {etaLabel}
        </span>
      )}
      <span className="text-text-sub/60 ml-auto text-sm">
        {t("aliveCount", language)}: {derived.aliveCount}/{gameState?.players?.length || 0}
      </span>
    </div>
  );
}
