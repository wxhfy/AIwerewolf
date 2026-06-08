"use client";

import React, { useState, useEffect } from "react";
import { Language, ViewMode } from "@/types";
import { Button } from "@/components/ui/Button";

export interface GameSettings {
  viewMode: ViewMode;
  language: Language;
  seed: number;
  modelProvider: string;
  modelName: string;
  apiKey: string;
  baseUrl: string;
  apiFormat: string;
  authEnvVar: string;
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentSettings: GameSettings;
  onSave: (settings: GameSettings) => void;
}

export function SettingsModal({ isOpen, onClose, currentSettings, onSave }: SettingsModalProps) {
  const [viewMode, setViewMode] = useState<ViewMode>(currentSettings.viewMode);
  const [language, setLanguage] = useState<Language>(currentSettings.language);
  const [seed, setSeed] = useState(currentSettings.seed);
  const [modelProvider, setModelProvider] = useState(currentSettings.modelProvider);
  const [modelName, setModelName] = useState(currentSettings.modelName);
  const [apiKey, setApiKey] = useState(currentSettings.apiKey);
  const [baseUrl, setBaseUrl] = useState(currentSettings.baseUrl);
  const [apiFormat, setApiFormat] = useState(currentSettings.apiFormat);
  const [authEnvVar, setAuthEnvVar] = useState(currentSettings.authEnvVar);
  const [showApiKey, setShowApiKey] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setViewMode(currentSettings.viewMode);
      setLanguage(currentSettings.language);
      setSeed(currentSettings.seed);
      setModelProvider(currentSettings.modelProvider);
      setModelName(currentSettings.modelName);
      setApiKey(currentSettings.apiKey);
      setBaseUrl(currentSettings.baseUrl);
      setApiFormat(currentSettings.apiFormat);
      setAuthEnvVar(currentSettings.authEnvVar);
    }
  }, [isOpen, currentSettings]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave({
      viewMode,
      language,
      seed: Number.isFinite(seed) ? Math.trunc(seed) : 7,
      modelProvider: modelProvider.trim() || "ark",
      modelName: modelName.trim() || "doubao-seed-2.0-pro",
      apiKey,
      baseUrl: baseUrl.trim().replace(/\/+$/, ""),
      apiFormat,
      authEnvVar,
    });
    onClose();
  };

  const t = (key: string) => {
      const translations: Record<string, { zh: string; en: string }> = {
      settings: { zh: "演示设置", en: "Demo Settings" },
      viewMode: { zh: "默认视角", en: "Default View" },
      moderatorView: { zh: "全局视角", en: "Global View" },
      publicView: { zh: "普通观众", en: "Audience" },
      moderatorDesc: { zh: "展示隐藏身份、夜间行动与关键决策", en: "Show hidden roles, night actions, and key decisions" },
      publicDesc: { zh: "只展示公开发言、投票和死亡结果", en: "Show public speeches, votes, and deaths" },
      languageSetting: { zh: "语言", en: "Language" },
      chinese: { zh: "中文", en: "Chinese" },
      english: { zh: "English", en: "English" },
      advanced: { zh: "高级选项", en: "Advanced Options" },
      seed: { zh: "Seed", en: "Seed" },
      seedDesc: { zh: "相同 Seed 可复现同一局配置", en: "Same seed reproduces the same setup" },
      random: { zh: "随机", en: "Random" },
      modelCall: { zh: "管理与测速", en: "Management & Speed Test" },
      provider: { zh: "供应商", en: "Provider" },
      modelName: { zh: "模型名称", en: "Model" },
      requestAddress: { zh: "请求地址", en: "Request Address" },
      fullUrl: { zh: "完整 URL", en: "Full URL" },
      endpointHint: { zh: "填写兼容 Claude API 的服务端点地址，不要以斜杠结尾", en: "Enter a Claude-compatible service endpoint. Do not end with a slash." },
      apiKey: { zh: "API Key", en: "API Key" },
      getApiKey: { zh: "获取 API Key", en: "Get API Key" },
      apiKeyDesc: { zh: "仅保存在本地浏览器，不显示在对局页面", en: "Stored locally only, never shown in the match UI" },
      apiKeyPlaceholder: { zh: "•••••••••••••••••••••••••••••••••••", en: "•••••••••••••••••••••••••••••••••••" },
      apiFormat: { zh: "API 格式", en: "API Format" },
      anthropicNative: { zh: "Anthropic Messages（原生）", en: "Anthropic Messages (Native)" },
      apiFormatDesc: { zh: "选择供应商 API 的输入格式", en: "Choose the provider API input format" },
      authField: { zh: "认证字段", en: "Authentication Field" },
      authTokenDefault: { zh: "ANTHROPIC_AUTH_TOKEN（默认）", en: "ANTHROPIC_AUTH_TOKEN (Default)" },
      authFieldDesc: { zh: "选择写入配置的认证环境变量名", en: "Choose the authentication environment variable name" },
      showApiKey: { zh: "显示", en: "Show" },
      hideApiKey: { zh: "隐藏", en: "Hide" },
      cancel: { zh: "取消", en: "Cancel" },
      save: { zh: "保存", en: "Save" },
    };
    return translations[key]?.[language] || key;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-2xl overflow-hidden rounded-card border border-border bg-cardBackground shadow-modal-strong">
        {/* Header */}
        <div className="relative border-b border-border bg-background/45 px-6 py-4">
          <h2 className="text-xl font-bold text-primary flex items-center gap-2">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 1v6m0 6v6m-5.196-13.804l4.243 4.243m0 6.122l4.243 4.243M1 12h6m6 0h6m-13.804 5.196l4.243-4.243m0-6.122l4.243-4.243" />
            </svg>
            {t("settings")}
          </h2>
          <button
            onClick={onClose}
            className="absolute top-4 right-4 w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/10 transition-colors text-text-sub/60 hover:text-text-sub"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="max-h-[72vh] space-y-6 overflow-y-auto px-6 py-6">
          {/* View Mode */}
          <div>
            <label className="block text-sm font-medium text-textPrimary mb-3">
              {t("viewMode")}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setViewMode(ViewMode.MODERATOR)}
                className={`relative p-4 rounded-lg border transition-all ${
                  viewMode === ViewMode.MODERATOR
                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                    : "border-border/40 hover:border-border/60 bg-background/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={viewMode === ViewMode.MODERATOR ? "text-primary" : "text-text-sub/60"}>
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <span className={`text-sm font-medium ${viewMode === ViewMode.MODERATOR ? "text-primary" : "text-text-sub"}`}>
                    {t("moderatorView")}
                  </span>
                </div>
                <p className="text-xs text-text-sub/60 text-left">{t("moderatorDesc")}</p>
              </button>

              <button
                onClick={() => setViewMode(ViewMode.PUBLIC)}
                className={`relative p-4 rounded-lg border transition-all ${
                  viewMode === ViewMode.PUBLIC
                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                    : "border-border/40 hover:border-border/60 bg-background/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={viewMode === ViewMode.PUBLIC ? "text-primary" : "text-text-sub/60"}>
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H7v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
                  </svg>
                  <span className={`text-sm font-medium ${viewMode === ViewMode.PUBLIC ? "text-primary" : "text-text-sub"}`}>
                    {t("publicView")}
                  </span>
                </div>
                <p className="text-xs text-text-sub/60 text-left">{t("publicDesc")}</p>
              </button>
            </div>
          </div>

          {/* Language */}
          <div>
            <label className="block text-sm font-medium text-textPrimary mb-3">
              {t("languageSetting")}
            </label>
            <div className="flex gap-3">
              <button
                onClick={() => setLanguage(Language.ZH)}
                className={`flex-1 px-4 py-3 rounded-lg border transition-all ${
                  language === "zh"
                    ? "border-primary bg-primary/10 text-primary font-medium"
                    : "border-border/40 hover:border-border/60 bg-background/50 text-text-sub"
                }`}
              >
                {t("chinese")}
              </button>
              <button
                onClick={() => setLanguage(Language.EN)}
                className={`flex-1 px-4 py-3 rounded-lg border transition-all ${
                  language === "en"
                    ? "border-primary bg-primary/10 text-primary font-medium"
                    : "border-border/40 hover:border-border/60 bg-background/50 text-text-sub"
                }`}
              >
                {t("english")}
              </button>
            </div>
          </div>

          {/* Advanced */}
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-textPrimary mb-1">
                {t("seed")}
              </label>
              <p className="mb-2 text-xs text-text-sub/60">{t("seedDesc")}</p>
              <div className="flex gap-2">
                <input
                  type="number"
                  value={Number.isFinite(seed) ? seed : 0}
                  onChange={(e) => setSeed(Number(e.target.value) || 0)}
                  className="h-11 flex-1 rounded-lg border border-border/40 bg-background/50 px-3.5 text-sm text-textPrimary outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setSeed(Math.floor(Math.random() * 1000))}
                  className="h-11"
                >
                  {t("random")}
                </Button>
              </div>
            </div>

            <div className="rounded-lg border border-border/40 bg-background/35 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-textPrimary">{t("modelCall")}</p>
                  <p className="text-xs text-text-sub/60">{t("apiKeyDesc")}</p>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("provider")}</span>
                  <select
                    value={modelProvider}
                    onChange={(e) => setModelProvider(e.target.value)}
                    className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 text-sm text-textPrimary outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                  >
                    <option value="anthropic">DeepSeek Claude Compatible</option>
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("modelName")}</span>
                  <input
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 text-sm text-textPrimary outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                  />
                </label>
              </div>
              <label className="mt-3 block">
                <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("requestAddress")}</span>
                <input
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value.replace(/\/+$/, ""))}
                  placeholder="https://api.deepseek.com/anthropic"
                  className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 text-sm text-textPrimary placeholder:text-text-sub/40 outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                />
                <p className="mt-1.5 text-xs text-text-sub/60">
                  <span className="font-medium text-text-sub">{t("fullUrl")}</span>
                  <span className="mx-1">·</span>
                  https://api.deepseek.com/anthropic
                </p>
                <p className="mt-1 text-xs text-primary/80">💡 {t("endpointHint")}</p>
              </label>
              <label className="mt-3 block">
                <div className="mb-1.5 flex items-center justify-between gap-3">
                  <span className="block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("apiKey")}</span>
                  <a
                    href="https://platform.deepseek.com/api_keys"
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-medium text-primary transition-colors hover:text-primaryHover"
                  >
                    {t("getApiKey")}
                  </a>
                </div>
                <div className="relative">
                  <input
                    type={showApiKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={t("apiKeyPlaceholder")}
                    className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 pr-20 text-sm text-textPrimary placeholder:text-text-sub/40 outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 text-xs font-medium text-text-sub/60 transition-colors hover:text-primary"
                  >
                    {showApiKey ? t("hideApiKey") : t("showApiKey")}
                  </button>
                </div>
              </label>
              <div className="mt-4 border-t border-border/40 pt-4">
                <p className="mb-3 text-sm font-medium text-textPrimary">{t("advanced")}</p>
                <div className="grid gap-3 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("apiFormat")}</span>
                    <select
                      value={apiFormat}
                      onChange={(e) => setApiFormat(e.target.value)}
                      className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 text-sm text-textPrimary outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="anthropic_messages">{t("anthropicNative")}</option>
                    </select>
                    <p className="mt-1.5 text-xs text-text-sub/60">{t("apiFormatDesc")}</p>
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-text-sub/70">{t("authField")}</span>
                    <select
                      value={authEnvVar}
                      onChange={(e) => setAuthEnvVar(e.target.value)}
                      className="h-11 w-full rounded-lg border border-border/40 bg-cardBackground px-3 text-sm text-textPrimary outline-none transition-all focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="ANTHROPIC_AUTH_TOKEN">{t("authTokenDefault")}</option>
                    </select>
                    <p className="mt-1.5 text-xs text-text-sub/60">{t("authFieldDesc")}</p>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 border-t border-border/40 bg-background/50 px-6 py-4">
          <Button variant="secondary" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button onClick={handleSave}>
            {t("save")}
          </Button>
        </div>
      </div>
    </div>
  );
}
