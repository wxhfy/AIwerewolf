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
    <div className="shrink-0 space-y-2 border-b border-border bg-cardBackground px-3 py-3 sm:px-5" data-phase-aware>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0" role="status" aria-live="polite">
          {actionText && <p className="mb-0.5 text-xs text-text-sub">{statusTitle}</p>}
          <p className="text-sm font-semibold leading-relaxed text-textPrimary">{actionText || statusTitle}</p>
        </div>
        <span className="shrink-0 rounded-badge border border-border bg-background px-2.5 py-1 text-xs tabular-nums text-text-sub">
          {t("aliveCount", language)} <strong className="font-semibold text-textPrimary">{derived.aliveCount}/{gameState?.players?.length || 0}</strong>
        </span>
      </div>
      {(thinkingLabel || queueLabel || etaLabel) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border pt-2 text-xs text-text-sub">
          {thinkingLabel && (
            <span data-testid="runtime-progress-current" className="inline-flex min-w-0 items-center gap-1.5 text-primary">
              <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
              {thinkingLabel}
            </span>
          )}
          {queueLabel && (
            <span data-testid="runtime-progress-queue">
              {queueLabel}
              {queue.length > 0 && (
                <span className="hidden sm:inline">
                  {" "}({queue.slice(0, 3).map((p) => (language === Language.ZH ? `${p.seat}号` : `#${p.seat}`)).join("、")}
                  {queue.length > 3 ? "…" : ""})
                </span>
              )}
            </span>
          )}
          {etaLabel && <span data-testid="runtime-progress-eta" className="ml-auto tabular-nums">{etaLabel}</span>}
        </div>
      )}
    </div>
  );
}
