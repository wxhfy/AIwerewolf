"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";

interface ReportMeta {
  hasHtml: boolean;
  hasMarkdown: boolean;
  status: string;
}

export default function GameReportPage() {
  const params = useParams<{ id: string }>();
  const gameId = params.id;
  const { language } = useAppContext();
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);

  const [meta, setMeta] = useState<ReportMeta | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  // Probe both endpoints with HEAD before rendering — when neither resource
  // exists yet (e.g. PublishedReview not generated) we want to show a clear
  // empty state instead of an iframe 404 + a broken download button.
  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const [htmlResp, mdResp] = await Promise.all([
          fetch(apiUrl(`/api/games/${gameId}/reviews/html`), { method: "GET" }),
          fetch(apiUrl(`/api/games/${gameId}/reviews.md?download=false`), { method: "GET" }),
        ]);
        if (cancelled) return;
        const status = htmlResp.ok || mdResp.ok ? "ready" : "missing";
        setMeta({ hasHtml: htmlResp.ok, hasMarkdown: mdResp.ok, status });
      } catch (err: any) {
        if (cancelled) return;
        setError(err?.message || "probe failed");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    probe();
    return () => {
      cancelled = true;
    };
  }, [gameId]);

  const htmlSrc = apiUrl(`/api/games/${gameId}/reviews/html`);
  const mdHref = apiUrl(`/api/games/${gameId}/reviews.md`);

  return (
    <main className="min-h-screen px-5 py-6" style={{ background: "var(--color-bg)" }}>
      <div className="mx-auto max-w-7xl space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-text-sub">Track B</p>
            <h1 className="font-display text-3xl font-bold text-primary">
              {t("对局复盘", "Game Review")}
            </h1>
            <p className="text-xs text-text-sub mt-1">game_id: {gameId}</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/"
              className="rounded-button border px-4 py-2 text-sm text-textPrimary"
              style={{ borderColor: "var(--color-border)" }}
            >
              {t("返回大厅", "Lobby")}
            </Link>
            <Link
              href="/evolution"
              className="rounded-button border px-4 py-2 text-sm text-textPrimary"
              style={{ borderColor: "var(--color-border)" }}
            >
              {t("进化看板", "Evolution")}
            </Link>
            {meta?.hasMarkdown && (
              <a
                href={mdHref}
                download={`review-${gameId}.md`}
                className="rounded-button bg-primary px-4 py-2 text-sm font-semibold text-white"
              >
                {t("下载 MD", "Download MD")}
              </a>
            )}
          </div>
        </header>

        {error && (
          <div className="rounded-card border border-danger/40 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        {isLoading && (
          <div className="rounded-card border px-4 py-12 text-center text-sm text-text-sub" style={{ borderColor: "var(--color-border)" }}>
            {t("加载复盘报告中...", "Loading review...")}
          </div>
        )}

        {!isLoading && meta?.status === "missing" && (
          <div className="rounded-card border px-4 py-12 text-center text-sm text-text-sub" style={{ borderColor: "var(--color-border)" }}>
            <p className="font-semibold text-textPrimary mb-2">
              {t("暂无复盘报告", "No review yet")}
            </p>
            <p>
              {t(
                "本局尚未生成 Track B 复盘。等对局结束并通过验证后会自动生成。",
                "This game has no published Track B review yet. Reviews are generated after the game ends and passes validation.",
              )}
            </p>
          </div>
        )}

        {!isLoading && meta?.hasHtml && (
          <div className="rounded-card overflow-hidden border bg-cardBackground" style={{ borderColor: "var(--color-border)" }}>
            <iframe
              src={htmlSrc}
              title={t("对局复盘 HTML", "Review HTML")}
              className="w-full"
              style={{ height: "calc(100vh - 220px)", minHeight: "600px", border: "none" }}
            />
          </div>
        )}

        {!isLoading && !meta?.hasHtml && meta?.hasMarkdown && (
          <div className="rounded-card border px-4 py-6 text-sm text-text-sub" style={{ borderColor: "var(--color-border)" }}>
            <p className="mb-3">
              {t(
                "本局只生成了 Markdown,没有 HTML 渲染。请点击右上角「下载 MD」获取。",
                "Only Markdown was generated for this game. Use the Download MD button above.",
              )}
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
