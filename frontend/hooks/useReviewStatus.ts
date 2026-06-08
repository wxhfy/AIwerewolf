"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

export interface ReviewStatus {
  game_id?: string;
  status: "idle" | "pending" | "ready" | "error";
  hasHtml: boolean;
  hasMarkdown: boolean;
  publishAllowed?: boolean;
  grade?: string | null;
  score?: number | null;
  publishedAt?: string | null;
}

interface UseReviewStatusOptions {
  enabled?: boolean;
  pollIntervalMs?: number;
}

const idleStatus: ReviewStatus = {
  status: "idle",
  hasHtml: false,
  hasMarkdown: false,
};

export function useReviewStatus(
  gameId: string | null | undefined,
  options: UseReviewStatusOptions = {},
) {
  const enabled = options.enabled ?? Boolean(gameId);
  const pollIntervalMs = options.pollIntervalMs ?? 3000;
  const [status, setStatus] = useState<ReviewStatus>(idleStatus);
  const [isLoading, setIsLoading] = useState(Boolean(enabled && gameId));
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState("");
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function probe() {
      if (!enabled || !gameId) {
        setStatus(idleStatus);
        setIsLoading(false);
        setIsChecking(false);
        setError("");
        setPollCount(0);
        return;
      }

      setIsChecking(true);
      try {
        const response = await fetch(apiUrl(`/api/games/${gameId}/reviews/status`), { method: "GET" });
        if (cancelled) return;
        if (!response.ok) {
          throw new Error(`reviewStatusFailed:${response.status}`);
        }
        const payload = await response.json();
        const hasHtml = Boolean(payload?.hasHtml);
        const hasMarkdown = Boolean(payload?.hasMarkdown);
        const ready = hasHtml || hasMarkdown || payload?.status === "ready";
        setStatus({
          game_id: payload?.game_id || gameId,
          status: ready ? "ready" : "pending",
          hasHtml,
          hasMarkdown,
          publishAllowed: Boolean(payload?.publishAllowed),
          grade: payload?.grade ?? null,
          score: typeof payload?.score === "number" ? payload.score : null,
          publishedAt: payload?.publishedAt ?? null,
        });
        setError("");
        if (!ready) {
          timer = setTimeout(() => {
            setPollCount((count) => count + 1);
            void probe();
          }, pollIntervalMs);
        }
      } catch (err: any) {
        if (!cancelled) {
          setStatus((current) => ({ ...current, status: "error" }));
          setError(err?.message || "review status probe failed");
          timer = setTimeout(() => {
            setPollCount((count) => count + 1);
            void probe();
          }, pollIntervalMs);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
          setIsChecking(false);
        }
      }
    }

    setIsLoading(Boolean(enabled && gameId));
    setPollCount(0);
    void probe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, gameId, pollIntervalMs]);

  return {
    status,
    isLoading,
    isChecking,
    error,
    pollCount,
    isReady: status.status === "ready",
  };
}
