"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/Button";

/* ── Constants ─────────────────────────────────────────────────── */

const MBTI_TYPES = [
  "INTJ", "INTP", "ENTJ", "ENTP", "INFJ", "INFP", "ENFJ", "ENFP",
  "ISTJ", "ISFJ", "ESTJ", "ESFJ", "ISTP", "ISFP", "ESTP", "ESFP",
];

const STYLE_LABELS = [
  "analytical", "persuasive", "aggressive", "insightful", "observant",
  "expressive", "meticulous", "provocative", "energetic", "academic",
  "commander", "sensitive", "interrogator", "gentle", "archivist",
  "tricky", "tactical", "precise", "observer", "rallier", "playful",
  "lyrical", "deconstructive", "caretaker", "strategist", "curious",
  "ranger", "matrix", "debater", "veteran", "theorist", "poetic",
  "cosmopolitan", "harmonizer", "still_water", "mediator", "anchor",
];

const HUMOR_OPTIONS = ["dry", "self_deprecating", "sarcastic", "warm", "none"];
const GENDERS = ["male", "female", "nonbinary"];

const EMPTY_FORM = {
  name: "", mbti: "INTJ", gender: "male", age: 25, basic_info: "",
  style_label: "analytical", vocabulary_style: "", speech_length_habit: "",
  reasoning_style: "", social_habit: "", humor_style: "dry",
  pressure_style: "", uncertainty_style: "", mistake_pattern: "",
  logic_style: "", trigger_topics: "", werewolf_experience: "中级",
};

const fieldClass = "w-full rounded-lg border border-border/40 bg-surface px-3 py-2.5 text-sm text-textPrimary placeholder:text-text-sub/30 focus:border-primary/60 focus:outline-none focus:ring-1 focus:ring-primary/20 transition";
const labelClass = "block text-xs font-medium text-text-sub/60 mb-1.5 uppercase tracking-wider";

/* ── Types ─────────────────────────────────────────────────────── */

interface PersonaItem {
  name: string; mbti: string; gender: string; age: number;
  basic_info: string; style_label: string;
  vocabulary_style: string; speech_length_habit: string;
  reasoning_style: string; social_habit: string; humor_style: string;
  pressure_style: string; uncertainty_style: string;
  mistake_pattern: string; logic_style: string;
  trigger_topics: string[]; werewolf_experience: string;
  system_prompt?: string;
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function PersonasPage() {
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [loading, setLoading] = useState(true);

  /* list */
  const load = useCallback(async () => {
    try { const res = await fetch("/api/personas"); setPersonas((await res.json()) || []); }
    catch { /* API unavailable */ }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  /* modals */
  const [detail, setDetail] = useState<PersonaItem | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-background">
      {/* ── Top bar ── */}
      <header className="flex items-center justify-between border-b border-border/30 bg-cardBackground/60 backdrop-blur-sm px-6 py-4">
        <div>
          <div className="flex items-center gap-4">
            <a href="/" className="text-sm text-text-sub/60 hover:text-primary transition">← 大厅</a>
            <h1 className="font-display text-xl font-bold text-primary tracking-wide">角色库</h1>
          </div>
          <p className="mt-0.5 pl-[72px] text-xs text-text-sub/60">
            {loading ? "加载中..." : `共 ${personas.length} 个角色 · 开局随机抽样`}
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setShowAdd(true)}>+ 新建角色</Button>
      </header>

      {/* ── Grid ── */}
      <div className="mx-auto max-w-6xl px-6 py-8">
        {loading ? (
          <div className="py-20 text-center text-sm text-text-sub/40">加载中...</div>
        ) : personas.length === 0 ? (
          <div className="py-20 text-center text-sm text-text-sub/40">还没有角色，点击「新建角色」开始</div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {personas.map((p) => (
              <Card key={p.name} persona={p}
                onClick={() => setDetail(p)}
                onDelete={() => setDeleteTarget(p.name)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Detail modal ── */}
      {detail && <DetailModal persona={detail} onClose={() => setDetail(null)} />}

      {/* ── Add modal ── */}
      {showAdd && (
        <AddModal
          onClose={() => setShowAdd(false)}
          onCreated={() => { setShowAdd(false); load(); }}
        />
      )}

      {/* ── Delete confirm ── */}
      {deleteTarget && (
        <DeleteConfirm name={deleteTarget}
          onCancel={() => setDeleteTarget(null)}
          onDeleted={() => { setDeleteTarget(null); load(); }}
        />
      )}
    </div>
  );
}

/* ── Card ──────────────────────────────────────────────────────── */

function Card({ persona: p, onClick, onDelete }: {
  persona: PersonaItem; onClick: () => void; onDelete: () => void;
}) {
  return (
    <div
      className="group cursor-pointer rounded-xl border border-border/40 bg-cardBackground/80 backdrop-blur-sm p-4 transition hover:border-primary/30 hover:shadow-[0_4px_20px_rgba(0,0,0,0.25)]"
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <h3 className="font-semibold text-textPrimary truncate">{p.name}</h3>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-text-sub/60">
            <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11px]">{p.mbti}</span>
            <span>{p.gender === "male" ? "♂" : p.gender === "female" ? "♀" : "⚧"}</span>
            <span>{p.age}岁</span>
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="rounded-md p-1 text-text-sub/20 transition hover:bg-red-500/10 hover:text-red-400 opacity-0 group-hover:opacity-100"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6h14"/></svg>
        </button>
      </div>
      {p.basic_info && (
        <p className="mt-2 text-sm text-text-sub/70 line-clamp-2 leading-relaxed">{p.basic_info}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {p.style_label && (
          <span className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-text-sub/50">{p.style_label}</span>
        )}
        {p.social_habit && (
          <span className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-text-sub/50">{p.social_habit}</span>
        )}
        {p.werewolf_experience && (
          <span className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-text-sub/50">{p.werewolf_experience}</span>
        )}
      </div>
    </div>
  );
}

/* ── Detail modal ──────────────────────────────────────────────── */

function DetailModal({ persona: p, onClose }: { persona: PersonaItem; onClose: () => void }) {
  const fields: [string, string | number | null][] = [
    ["MBTI", p.mbti], ["性别", p.gender === "male" ? "男" : p.gender === "female" ? "女" : "非二元"],
    ["年龄", p.age], ["桌面风格", p.style_label], ["经验", p.werewolf_experience],
    ["用词风格", p.vocabulary_style], ["发言长度", p.speech_length_habit],
    ["推理风格", p.reasoning_style], ["社交习惯", p.social_habit],
    ["幽默风格", p.humor_style], ["逻辑风格", p.logic_style],
    ["压力反应", p.pressure_style], ["不确定时", p.uncertainty_style],
    ["典型弱点", p.mistake_pattern],
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm pt-10 pb-10" onClick={onClose}>
      <div className="mx-4 w-full max-w-lg rounded-2xl border border-border/40 bg-cardBackground p-6 shadow-[0_16px_64px_rgba(0,0,0,0.5)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-display text-xl font-bold text-primary">{p.name}</h2>
            <p className="mt-1 text-sm text-text-sub/70 leading-relaxed">{p.basic_info || "（无背景描述）"}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-text-sub/40 hover:text-textPrimary transition">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2">
          {fields.map(([label, value]) => value ? (
            <div key={label} className="flex justify-between items-center py-1.5 border-b border-border/20">
              <span className="text-xs text-text-sub/50">{label}</span>
              <span className="text-sm text-textPrimary font-medium">{String(value)}</span>
            </div>
          ) : null)}
        </div>
        {p.trigger_topics && p.trigger_topics.length > 0 && (
          <div className="mt-4">
            <span className="text-xs text-text-sub/50 uppercase tracking-wider">触发话题</span>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {(Array.isArray(p.trigger_topics) ? p.trigger_topics : [p.trigger_topics]).map((t: string, i: number) => (
                <span key={i} className="rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary/80">{t}</span>
              ))}
            </div>
          </div>
        )}
        <div className="mt-6 flex justify-end">
          <Button variant="secondary" size="sm" onClick={onClose}>关闭</Button>
        </div>
      </div>
    </div>
  );
}

/* ── Add modal ─────────────────────────────────────────────────── */

function AddModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const save = async () => {
    if (!form.name.trim()) { setErr("请填写角色名字"); return; }
    setSaving(true); setErr("");
    try {
      const body = {
        ...form, age: Number(form.age) || 25,
        trigger_topics: form.trigger_topics.split(/[,，]/).map(s => s.trim()).filter(Boolean),
      };
      const res = await fetch("/api/personas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || `${res.status}`); }
      onCreated();
    } catch (e: any) { setErr(e.message || "创建失败"); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm pt-10 pb-10" onClick={onClose}>
      <div className="mx-4 w-full max-w-2xl rounded-2xl border border-border/40 bg-cardBackground p-6 shadow-[0_16px_64px_rgba(0,0,0,0.5)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg font-bold text-primary">新建角色</h2>
          <button onClick={onClose} className="rounded-lg p-2 text-text-sub/40 hover:text-textPrimary transition">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
          </button>
        </div>

        {err && <div className="mb-4 rounded-lg bg-red-500/10 border border-red-500/20 px-4 py-2.5 text-sm text-red-400">{err}</div>}

        <Section title="基础信息" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className={labelClass}>名字 *</label>
            <input value={form.name} onChange={e => setForm({...form, name: e.target.value})} className={fieldClass} placeholder="给角色起名" />
          </div>
          <div>
            <label className={labelClass}>MBTI</label>
            <select value={form.mbti} onChange={e => setForm({...form, mbti: e.target.value})} className={fieldClass}>
              {MBTI_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>性别</label>
            <select value={form.gender} onChange={e => setForm({...form, gender: e.target.value})} className={fieldClass}>
              {GENDERS.map(g => <option key={g} value={g}>{g === "male" ? "男" : g === "female" ? "女" : "非二元"}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>年龄</label>
            <input type="number" value={form.age} min={10} max={99} onChange={e => setForm({...form, age: parseInt(e.target.value)||0})} className={fieldClass} />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClass}>背景故事</label>
            <textarea value={form.basic_info} rows={2} onChange={e => setForm({...form, basic_info: e.target.value})} className={fieldClass} placeholder="一两句话描述职业、性格特点。" />
          </div>
          <div>
            <label className={labelClass}>桌面风格</label>
            <select value={form.style_label} onChange={e => setForm({...form, style_label: e.target.value})} className={fieldClass}>
              <option value="">-- 选一个 --</option>
              {STYLE_LABELS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>狼人杀经验</label>
            <input value={form.werewolf_experience} onChange={e => setForm({...form, werewolf_experience: e.target.value})} className={fieldClass} placeholder="如：中级，靠直觉打牌" />
          </div>
        </div>

        <Section title="说话风格" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className={labelClass}>用词风格</label><input value={form.vocabulary_style} onChange={e => setForm({...form, vocabulary_style: e.target.value})} className={fieldClass} placeholder="如：用词精准、数据感强" /></div>
          <div><label className={labelClass}>发言长度</label><input value={form.speech_length_habit} onChange={e => setForm({...form, speech_length_habit: e.target.value})} className={fieldClass} placeholder="如：简洁有力" /></div>
          <div><label className={labelClass}>推理风格</label><input value={form.reasoning_style} onChange={e => setForm({...form, reasoning_style: e.target.value})} className={fieldClass} placeholder="如：逻辑链条式" /></div>
          <div><label className={labelClass}>社交习惯</label><input value={form.social_habit} onChange={e => setForm({...form, social_habit: e.target.value})} className={fieldClass} placeholder="如：独立分析，不轻易跟票" /></div>
          <div>
            <label className={labelClass}>幽默风格</label>
            <select value={form.humor_style} onChange={e => setForm({...form, humor_style: e.target.value})} className={fieldClass}>
              {HUMOR_OPTIONS.map(h => <option key={h} value={h}>{h}</option>)}
            </select>
          </div>
          <div><label className={labelClass}>逻辑风格</label><input value={form.logic_style} onChange={e => setForm({...form, logic_style: e.target.value})} className={fieldClass} placeholder="如：证据链 + 时间线核对" /></div>
        </div>

        <Section title="压力与社交" />
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className={labelClass}>被质疑时</label><input value={form.pressure_style} onChange={e => setForm({...form, pressure_style: e.target.value})} className={fieldClass} placeholder="如：列出更多证据来反驳" /></div>
          <div><label className={labelClass}>不确定时</label><input value={form.uncertainty_style} onChange={e => setForm({...form, uncertainty_style: e.target.value})} className={fieldClass} placeholder="如：直接承认不确定" /></div>
          <div className="sm:col-span-2"><label className={labelClass}>典型弱点</label><input value={form.mistake_pattern} onChange={e => setForm({...form, mistake_pattern: e.target.value})} className={fieldClass} placeholder="如：偶尔过度自信忽略了情绪线索" /></div>
          <div className="sm:col-span-2"><label className={labelClass}>触发话题（逗号分隔）</label><input value={form.trigger_topics} onChange={e => setForm({...form, trigger_topics: e.target.value})} className={fieldClass} placeholder="如：票型异常, 前后矛盾, 信息差" /></div>
        </div>

        <div className="mt-8 flex items-center justify-end gap-3 border-t border-border/30 pt-5">
          <Button variant="secondary" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" onClick={save} disabled={saving}>{saving ? "创建中..." : "创建角色"}</Button>
        </div>
      </div>
    </div>
  );
}

/* ── Delete confirm ────────────────────────────────────────────── */

function DeleteConfirm({ name, onCancel, onDeleted }: { name: string; onCancel: () => void; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const remove = async () => {
    setDeleting(true);
    await fetch(`/api/personas/${encodeURIComponent(name)}`, { method: "DELETE" });
    onDeleted();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onCancel}>
      <div className="mx-4 w-full max-w-sm rounded-2xl border border-border/40 bg-cardBackground p-6 text-center shadow-[0_16px_64px_rgba(0,0,0,0.5)]" onClick={e => e.stopPropagation()}>
        <p className="text-sm text-textPrimary">确定要删除 <span className="font-semibold text-primary">{name}</span> 吗？</p>
        <p className="mt-1 text-xs text-text-sub/50">此操作不可撤销</p>
        <div className="mt-5 flex justify-center gap-3">
          <Button variant="secondary" size="sm" onClick={onCancel}>取消</Button>
          <button onClick={remove} disabled={deleting}
            className="inline-flex items-center justify-center rounded-button px-4 py-2 text-sm font-medium transition-all duration-150 bg-red-500 text-white hover:bg-red-600 active:scale-[0.98] disabled:opacity-50">
            {deleting ? "删除中..." : "确认删除"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Section divider ───────────────────────────────────────────── */

function Section({ title }: { title: string }) {
  return (
    <div className="mb-4 mt-6 flex items-center gap-3 first:mt-0">
      <span className="text-xs font-semibold uppercase tracking-[0.15em] text-text-sub/40">{title}</span>
      <div className="h-px flex-1 bg-border/30" />
    </div>
  );
}
