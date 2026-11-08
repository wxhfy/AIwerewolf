import React from "react";
import Link from "next/link";

export default function AdminDashboardPage() {
  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-xl font-bold text-slate-800">控制台概览</h2>
        <p className="mt-1 text-sm text-slate-500">
          AI Werewolf 管理与评测控制台。用于真 LLM 区分度实验分析、角色库定义及系统权限管控。
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Card 1: Eval Dashboard */}
        <Link
          href="/admin/eval"
          className="group block rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-400 hover:shadow"
        >
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              Track B 评估总览
            </h3>
            <span className="text-xs text-slate-400 group-hover:translate-x-0.5 transition-transform">
              →
            </span>
          </div>
          <p className="mt-2 text-xs text-slate-500 leading-relaxed">
            真 LLM 评分区分度（Cohen&apos;s d、Welch t-test）与 Track B 持久层聚合指标图表。
          </p>
          <div className="mt-4 flex items-center gap-2 text-[11px] font-mono text-slate-400">
            <span>/api/eval/role-scores</span>
            <span>·</span>
            <span>/api/metrics/aggregate</span>
          </div>
        </Link>

        {/* Card 2: Personas */}
        <Link
          href="/admin/personas"
          className="group block rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-slate-400 hover:shadow"
        >
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-slate-900 group-hover:text-blue-600 transition-colors">
              角色库管理
            </h3>
            <span className="text-xs text-slate-400 group-hover:translate-x-0.5 transition-transform">
              →
            </span>
          </div>
          <p className="mt-2 text-xs text-slate-500 leading-relaxed">
            管理开局随机抽样的角色人设、MBTI 性格标签、说话风格以及压力应对模式。
          </p>
          <div className="mt-4 flex items-center gap-2 text-[11px] font-mono text-slate-400">
            <span>/api/personas</span>
          </div>
        </Link>
      </div>

      {/* System Status info */}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="text-sm font-semibold text-slate-800">Slice 1 权限与视图约束说明</h3>
        <ul className="mt-3 space-y-2 text-xs text-slate-600">
          <li className="flex items-start gap-2">
            <span className="text-emerald-500 font-bold">✓</span>
            <span>默认公共视图：观战视角严格隐藏未出局角色的底牌及私有行动。</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-emerald-500 font-bold">✓</span>
            <span>上帝视角保护：仅在携带 view=god 且服务端鉴权通过时放行，未授权自动降级为公开视角。</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-emerald-500 font-bold">✓</span>
            <span>赛后身份揭示：对局产生胜者后，由公开快照完成身份全量披露。</span>
          </li>
        </ul>
      </section>
    </div>
  );
}
