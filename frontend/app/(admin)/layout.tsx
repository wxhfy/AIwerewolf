import React from "react";
import Link from "next/link";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen [min-height:100dvh] flex flex-col bg-slate-50 text-slate-900 font-sans">
      {/* ── Top Header: Visible "管理后台" ── */}
      <header className="h-14 border-b border-slate-200 bg-white px-6 flex items-center justify-between z-20 shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded bg-slate-800 text-white flex items-center justify-center font-bold text-xs">
            AW
          </div>
          <h1 className="text-base font-semibold text-slate-800 tracking-wide">
            管理后台
          </h1>
          <span className="text-[11px] px-2 py-0.5 rounded bg-slate-100 text-slate-500 font-mono">
            Admin Console
          </span>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <Link
            href="/"
            className="text-slate-600 hover:text-slate-900 flex items-center gap-1.5 transition-colors text-xs font-medium"
          >
            <span>← 返回对局大厅</span>
          </Link>
        </div>
      </header>

      {/* ── Body: Left Nav + Content ── */}
      <div className="flex flex-1 min-h-0">
        <aside className="w-56 border-r border-slate-200 bg-white flex flex-col shrink-0 p-4 gap-1">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 px-3 mb-2">
            控制台模块
          </div>
          <Link
            href="/admin"
            className="px-3 py-2 rounded-md text-sm font-medium text-slate-700 hover:bg-slate-100 transition-colors"
          >
            控制台概览
          </Link>
          <Link
            href="/admin/eval"
            className="px-3 py-2 rounded-md text-sm font-medium text-slate-700 hover:bg-slate-100 transition-colors"
          >
            Track B 评估总览
          </Link>
          <Link
            href="/admin/personas"
            className="px-3 py-2 rounded-md text-sm font-medium text-slate-700 hover:bg-slate-100 transition-colors"
          >
            角色库管理
          </Link>
        </aside>

        <main className="flex-1 min-h-0 overflow-y-auto bg-slate-50 p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
