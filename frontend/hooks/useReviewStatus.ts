"use client";

import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";

export type ReviewLifecycleStatus =
  | "not_scheduled"
  | "pending"
  | "running"
  | "published"
  | "failed";

export interface ReviewStatus {
  game_id?: string;
  status: "idle" | "pending" | "ready" | "failed" | "not_scheduled" | "error";
  lifecycle_status?: ReviewLifecycleStatus | string;
  lifecycleStatus?: ReviewLifecycleStatus | string;
  retryable?: boolean;
  attempts?: number;
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
  lifecycleStatus: undefined,
  lifecycle_status: undefined,
  retryable: false,
  attempts: 0,
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
    let errorRetries = 0;
    const MAX_ERROR_RETRIES = 2;

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
        errorRetries = 0;
        const payload = await response.json();
        const hasHtml = Boolean(payload?.hasHtml);
        const hasMarkdown = Boolean(payload?.hasMarkdown);
        const lifecycleStatus: ReviewLifecycleStatus | string | undefined = payload?.lifecycle_status;
        const retryable = Boolean(payload?.retryable);
        const attempts = typeof payload?.attempts === "number" ? payload.attempts : 0;

        const isReady = hasHtml || hasMarkdown || payload?.status === "ready" || lifecycleStatus === "published";
        const isFailed = !isReady && (lifecycleStatus === "failed" || payload?.status === "failed");
        const isNotScheduled = !isReady && !isFailed && lifecycleStatus === "not_scheduled";
        const isPending = !isReady && !isFailed && !isNotScheduled && (
          lifecycleStatus === "pending" ||
          lifecycleStatus === "running" ||
          (!lifecycleStatus && payload?.status === "pending")
        );

        let nextStatus: ReviewStatus["status"] = "pending";
        if (isReady) {
          nextStatus = "ready";
        } else if (isFailed) {
          nextStatus = "failed";
        } else if (isNotScheduled) {
          nextStatus = "not_scheduled";
        } else if (isPending) {
          nextStatus = "pending";
        } else {
          nextStatus = "not_scheduled";
        }

        setStatus({
          game_id: payload?.game_id || gameId,
          status: nextStatus,
          lifecycleStatus,
          lifecycle_status: lifecycleStatus,
          retryable,
          attempts,
          hasHtml,
          hasMarkdown,
          publishAllowed: Boolean(payload?.publishAllowed),
          grade: payload?.grade ?? null,
          score: typeof payload?.score === "number" ? payload.score : null,
          publishedAt: payload?.publishedAt ?? null,
        });
        setError("");

        // Polling should CONTINUE only while analysis is actually in progress (lifecycle pending or running, and not ready).
        // STOP polling when any of these is true:
        // - analysis not enabled: lifecycle_status === "not_scheduled"
        // - lifecycle_status === "failed"
        // - retryable === false (when failed)
        // - review is ready (hasHtml / hasMarkdown / status==="ready" / lifecycle_status==="published")
        const shouldPoll = nextStatus === "pending";
        if (shouldPoll) {
          timer = setTimeout(() => {
            setPollCount((count) => count + 1);
            void probe();
          }, pollIntervalMs);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "review status probe failed");
          if (errorRetries < MAX_ERROR_RETRIES) {
            errorRetries += 1;
            timer = setTimeout(() => {
              setPollCount((count) => count + 1);
              void probe();
            }, pollIntervalMs);
          } else {
            setStatus((current) => ({ ...current, status: "error" }));
          }
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

  const isReady = status.status === "ready";
  const isPending = status.status === "pending";
  const failed = status.status === "failed";
  const analysisDisabled = status.status === "not_scheduled";

  return {
    status,
    isLoading,
    isChecking,
    error,
    pollCount,
    isReady,
    isPending,
    analysisDisabled,
    isAnalysisDisabled: analysisDisabled,
    failed,
    isFailed: failed,
    retryable: Boolean(status.retryable),
    attempts: status.attempts ?? 0,
    lifecycleStatus: status.lifecycleStatus,
  };
}
