"use client";

import { useEffect, useState, useCallback } from "react";

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

const GENDERS = ["male", "female", "nonbinary"];

const EMPTY_FORM = {
  name: "", mbti: "INTJ", gender: "male", age: 25, basic_info: "",
  style_label: "analytical", vocabulary_style: "", speech_length_habit: "",
  reasoning_style: "", social_habit: "", humor_style: "dry",
  pressure_style: "", uncertainty_style: "", mistake_pattern: "",
  logic_style: "", trigger_topics: "", werewolf_experience: "中级",
};

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

export default function PersonasPage() {
  const [personas, setPersonas] = useState<PersonaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/personas");
      const data = await res.json();
      setPersonas(data || []);
    } catch {
      // API not ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const notify = (type: "ok" | "err", text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 3000);
  };

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setEditing(false);
    setShowForm(false);
  };

  const openNew = () => {
    setForm(EMPTY_FORM);
    setEditing(false);
    setShowForm(true);
  };

  const openEdit = (p: PersonaItem) => {
    setForm({
      name: p.name, mbti: p.mbti, gender: p.gender, age: p.age,
      basic_info: p.basic_info || "", style_label: p.style_label || "",
      vocabulary_style: p.vocabulary_style || "",
      speech_length_habit: p.speech_length_habit || "",
      reasoning_style: p.reasoning_style || "",
      social_habit: p.social_habit || "", humor_style: p.humor_style || "",
      pressure_style: p.pressure_style || "",
      uncertainty_style: p.uncertainty_style || "",
      mistake_pattern: p.mistake_pattern || "",
      logic_style: p.logic_style || "",
      trigger_topics: (p.trigger_topics || []).join(", "),
      werewolf_experience: p.werewolf_experience || "",
    });
    setEditing(true);
    setShowForm(true);
  };

  const save = async () => {
    if (!form.name.trim()) {
      notify("err", "名字不能为空");
      return;
    }
    setSaving(true);
    try {
      const body = {
        ...form,
        age: Number(form.age) || 25,
        trigger_topics: form.trigger_topics
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean),
      };
      const method = editing ? "PUT" : "POST";
      const url = editing ? `/api/personas/${encodeURIComponent(form.name)}` : "/api/personas";
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `${res.status}`);
      }
      notify("ok", editing ? `已更新 ${form.name}` : `已创建 ${form.name}`);
      resetForm();
      load();
    } catch (e: any) {
      notify("err", e.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (name: string) => {
    try {
      const res = await fetch(`/api/personas/${encodeURIComponent(name)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`${res.status}`);
      notify("ok", `已删除 ${name}`);
      setDeleteConfirm(null);
      load();
    } catch (e: any) {
      notify("err", e.message || "删除失败");
    }
  };

  if (loading) return <div className="p-8 text-text-sub">加载中...</div>;

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl font-bold text-primary">角色库管理</h1>
            <p className="mt-1 text-sm text-text-sub">
              共 {personas.length} 个角色 · 新增角色会自动写入数据库，开局随机抽样
            </p>
          </div>
          <button
            onClick={openNew}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary/80"
          >
            + 新建角色
          </button>
        </div>

        {/* Message */}
        {message && (
          <div className={`mb-4 rounded-lg px-4 py-2 text-sm font-medium ${
            message.type === "ok" ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
          }`}>
            {message.text}
          </div>
        )}

        {/* Persona Grid */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {personas.map((p) => (
            <div
              key={p.name}
              className="rounded-xl border border-border bg-cardBackground p-4 transition hover:border-primary/30"
            >
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <h3 className="font-semibold text-textPrimary">{p.name}</h3>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-text-sub">
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono">{p.mbti}</span>
                    <span>{p.gender}</span>
                    <span>{p.age}岁</span>
                    {p.style_label && <span>· {p.style_label}</span>}
                  </div>
                </div>
              </div>
              {p.basic_info && (
                <p className="mt-2 text-sm text-text-sub line-clamp-2">{p.basic_info}</p>
              )}
              <div className="mt-3 flex items-center gap-2 text-xs">
                {p.vocabulary_style && (
                  <span className="rounded bg-surface px-1.5 py-0.5 text-text-sub/70">{p.vocabulary_style}</span>
                )}
                {p.social_habit && (
                  <span className="rounded bg-surface px-1.5 py-0.5 text-text-sub/70">{p.social_habit}</span>
                )}
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => openEdit(p)}
                  className="rounded-md bg-surface px-3 py-1 text-xs font-medium text-textPrimary transition hover:bg-primary/10"
                >
                  编辑
                </button>
                <button
                  onClick={() => setDeleteConfirm(p.name)}
                  className="rounded-md bg-red-500/10 px-3 py-1 text-xs font-medium text-red-400 transition hover:bg-red-500/20"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Empty state */}
        {personas.length === 0 && (
          <div className="py-20 text-center text-text-sub">
            还没有角色，点击「新建角色」开始
          </div>
        )}
      </div>

      {/* Form Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 pt-10 pb-10">
          <div className="mx-4 w-full max-w-2xl rounded-2xl border border-border bg-cardBackground p-6">
            <h2 className="mb-4 font-display text-lg font-bold text-primary">
              {editing ? `编辑 ${form.name}` : "新建角色"}
            </h2>

            <div className="grid gap-4 sm:grid-cols-2">
              {/* Row 1: name + mbti */}
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">名字 *</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  disabled={editing}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none disabled:opacity-50"
                  placeholder="如：小爪"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">MBTI</label>
                <select
                  value={form.mbti}
                  onChange={(e) => setForm({ ...form, mbti: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                >
                  {MBTI_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              {/* Row 2: gender + age */}
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">性别</label>
                <select
                  value={form.gender}
                  onChange={(e) => setForm({ ...form, gender: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                >
                  {GENDERS.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">年龄</label>
                <input
                  type="number"
                  value={form.age}
                  onChange={(e) => setForm({ ...form, age: parseInt(e.target.value) || 0 })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  min={10} max={99}
                />
              </div>

              {/* Row 3: style_label + werewolf_experience */}
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">桌面风格</label>
                <select
                  value={form.style_label}
                  onChange={(e) => setForm({ ...form, style_label: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                >
                  <option value="">-- 选一个 --</option>
                  {STYLE_LABELS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">狼人杀经验</label>
                <input
                  value={form.werewolf_experience}
                  onChange={(e) => setForm({ ...form, werewolf_experience: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：中级，靠直觉打牌"
                />
              </div>
            </div>

            {/* basic_info */}
            <div className="mt-4">
              <label className="mb-1 block text-xs font-medium text-text-sub">背景故事</label>
              <textarea
                value={form.basic_info}
                onChange={(e) => setForm({ ...form, basic_info: e.target.value })}
                rows={2}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                placeholder="如：数据分析师，习惯用逻辑和概率做判断，讨厌情绪化的发言。"
              />
            </div>

            {/* Style fields */}
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">用词风格</label>
                <input
                  value={form.vocabulary_style}
                  onChange={(e) => setForm({ ...form, vocabulary_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：用词精准、数据感强"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">发言长度习惯</label>
                <input
                  value={form.speech_length_habit}
                  onChange={(e) => setForm({ ...form, speech_length_habit: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：简洁有力"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">推理风格</label>
                <input
                  value={form.reasoning_style}
                  onChange={(e) => setForm({ ...form, reasoning_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：逻辑链条式"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">社交习惯</label>
                <input
                  value={form.social_habit}
                  onChange={(e) => setForm({ ...form, social_habit: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：独立分析，不轻易跟票"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">幽默风格</label>
                <select
                  value={form.humor_style}
                  onChange={(e) => setForm({ ...form, humor_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                >
                  <option value="">-- 选一个 --</option>
                  {["dry", "self_deprecating", "sarcastic", "warm", "none"].map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">压力下反应</label>
                <input
                  value={form.pressure_style}
                  onChange={(e) => setForm({ ...form, pressure_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：被质疑时列出更多证据"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">不确定时</label>
                <input
                  value={form.uncertainty_style}
                  onChange={(e) => setForm({ ...form, uncertainty_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：直接承认，给出最优推测"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">典型弱点</label>
                <input
                  value={form.mistake_pattern}
                  onChange={(e) => setForm({ ...form, mistake_pattern: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：偶尔过度自信忽略情绪线索"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-text-sub">逻辑风格</label>
                <input
                  value={form.logic_style}
                  onChange={(e) => setForm({ ...form, logic_style: e.target.value })}
                  className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                  placeholder="如：前置假设 + 反证排除"
                />
              </div>
            </div>

            {/* trigger_topics */}
            <div className="mt-4">
              <label className="mb-1 block text-xs font-medium text-text-sub">
                触发话题（逗号分隔）
              </label>
              <input
                value={form.trigger_topics}
                onChange={(e) => setForm({ ...form, trigger_topics: e.target.value })}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-textPrimary focus:border-primary focus:outline-none"
                placeholder="如：票型异常, 前后矛盾, 信息差"
              />
            </div>

            {/* Actions */}
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={resetForm}
                className="rounded-lg bg-surface px-4 py-2 text-sm font-medium text-text-sub transition hover:bg-border"
              >
                取消
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="rounded-lg bg-primary px-5 py-2 text-sm font-semibold text-white transition hover:bg-primary/80 disabled:opacity-50"
              >
                {saving ? "保存中..." : editing ? "更新" : "创建"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirm */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 w-full max-w-sm rounded-2xl border border-border bg-cardBackground p-6 text-center">
            <p className="text-sm text-textPrimary">
              确定要删除 <span className="font-semibold text-primary">{deleteConfirm}</span> 吗？
            </p>
            <p className="mt-1 text-xs text-text-sub">此操作不可撤销</p>
            <div className="mt-4 flex justify-center gap-3">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="rounded-lg bg-surface px-4 py-2 text-sm font-medium text-text-sub"
              >
                取消
              </button>
              <button
                onClick={() => remove(deleteConfirm)}
                className="rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-500/80"
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
