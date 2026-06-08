"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiUrl } from "@/lib/api";
import { useAppContext } from "@/context/AppContext";
import { useReviewStatus } from "@/hooks/useReviewStatus";

export default function GameReportPage() {
  const params = useParams<{ id: string }>();
  const gameId = params.id;
  const { language } = useAppContext();
  const t = (zh: string, en: string) => (language === "zh" ? zh : en);
  const reviewStatus = useReviewStatus(gameId);
  const meta = reviewStatus.status;

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
            {meta.hasMarkdown && (
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

        {reviewStatus.error && (
          <div className="rounded-card border border-danger/40 px-4 py-3 text-sm text-danger">
            {reviewStatus.error}
          </div>
        )}

        {reviewStatus.isLoading && (
          <div className="rounded-card border px-4 py-12 text-center text-sm text-text-sub" style={{ borderColor: "var(--color-border)" }}>
            {t("加载复盘报告中...", "Loading review...")}
          </div>
        )}

        {!reviewStatus.isLoading && meta.status !== "ready" && (
          <div className="rounded-card border px-4 py-12 text-center text-sm text-text-sub" style={{ borderColor: "var(--color-border)" }}>
            <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
            <p className="font-semibold text-textPrimary mb-2">
              {t("复盘报告生成中", "Generating review")}
            </p>
            <p>
              {t(
                "后端正在生成或发布 Track B 复盘。生成完成后页面会自动切换为可查看状态。",
                "The backend is generating or publishing the Track B review. This page will switch to the report when it is ready.",
              )}
            </p>
            <p className="mt-3 text-[11px] text-text-sub/60">
              {t("轮询次数", "Polls")}: {reviewStatus.pollCount}
            </p>
          </div>
        )}

        {!reviewStatus.isLoading && meta.hasHtml && (
          <div className="rounded-card overflow-hidden border bg-cardBackground" style={{ borderColor: "var(--color-border)" }}>
            <iframe
              src={htmlSrc}
              title={t("对局复盘 HTML", "Review HTML")}
              className="w-full"
              style={{ height: "calc(100vh - 220px)", minHeight: "600px", border: "none" }}
            />
          </div>
        )}

        {!reviewStatus.isLoading && !meta.hasHtml && meta.hasMarkdown && (
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
