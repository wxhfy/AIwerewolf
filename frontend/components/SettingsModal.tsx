"use client";

import React, { useState, useEffect } from "react";
import { Language } from "@/types";

export interface GameSettings {
  viewMode: "moderator" | "public";
  language: Language;
  customApiKey: string;
}

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentSettings: GameSettings;
  onSave: (settings: GameSettings) => void;
}

export function SettingsModal({ isOpen, onClose, currentSettings, onSave }: SettingsModalProps) {
  const [viewMode, setViewMode] = useState<"moderator" | "public">(currentSettings.viewMode);
  const [language, setLanguage] = useState<Language>(currentSettings.language);
  const [customApiKey, setCustomApiKey] = useState(currentSettings.customApiKey);
  const [showApiKey, setShowApiKey] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setViewMode(currentSettings.viewMode);
      setLanguage(currentSettings.language);
      setCustomApiKey(currentSettings.customApiKey);
    }
  }, [isOpen, currentSettings]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave({ viewMode, language, customApiKey });
    onClose();
  };

  const t = (key: string) => {
    const translations: Record<string, { zh: string; en: string }> = {
      settings: { zh: "设置", en: "Settings" },
      viewMode: { zh: "视角模式", en: "View Mode" },
      moderatorView: { zh: "主持视角", en: "Moderator View" },
      publicView: { zh: "全局视角", en: "Public View" },
      moderatorDesc: { zh: "查看所有角色和私密信息", en: "See all roles and private info" },
      publicDesc: { zh: "仅查看公开信息", en: "Public information only" },
      languageSetting: { zh: "语言设置", en: "Language" },
      chinese: { zh: "中文", en: "Chinese" },
      english: { zh: "English", en: "English" },
      apiKey: { zh: "自定义 API Key", en: "Custom API Key" },
      apiKeyDesc: { zh: "用于后续对局的 LLM 调用", en: "For LLM calls in future games" },
      apiKeyPlaceholder: { zh: "留空使用默认配置", en: "Leave empty for default" },
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
      <div className="relative w-full max-w-md bg-card border border-border/40 rounded-lg shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="relative px-6 py-4 border-b border-border/40 bg-gradient-to-r from-primary/10 to-transparent">
          <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full blur-3xl" />
          <h2 className="relative text-xl font-bold text-primary flex items-center gap-2">
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
        <div className="px-6 py-6 space-y-6 max-h-[70vh] overflow-y-auto">
          {/* View Mode */}
          <div>
            <label className="block text-sm font-medium text-text-primary mb-3">
              {t("viewMode")}
            </label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setViewMode("moderator")}
                className={`relative p-4 rounded-lg border transition-all ${
                  viewMode === "moderator"
                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                    : "border-border/40 hover:border-border/60 bg-background/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={viewMode === "moderator" ? "text-primary" : "text-text-sub/60"}>
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  <span className={`text-sm font-medium ${viewMode === "moderator" ? "text-primary" : "text-text-sub"}`}>
                    {t("moderatorView")}
                  </span>
                </div>
                <p className="text-xs text-text-sub/60 text-left">{t("moderatorDesc")}</p>
              </button>

              <button
                onClick={() => setViewMode("public")}
                className={`relative p-4 rounded-lg border transition-all ${
                  viewMode === "public"
                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                    : "border-border/40 hover:border-border/60 bg-background/50"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={viewMode === "public" ? "text-primary" : "text-text-sub/60"}>
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H7v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
                  </svg>
                  <span className={`text-sm font-medium ${viewMode === "public" ? "text-primary" : "text-text-sub"}`}>
                    {t("publicView")}
                  </span>
                </div>
                <p className="text-xs text-text-sub/60 text-left">{t("publicDesc")}</p>
              </button>
            </div>
          </div>

          {/* Language */}
          <div>
            <label className="block text-sm font-medium text-text-primary mb-3">
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

          {/* Custom API Key */}
          <div>
            <label className="block text-sm font-medium text-text-primary mb-1">
              {t("apiKey")}
            </label>
            <p className="text-xs text-text-sub/60 mb-3">{t("apiKeyDesc")}</p>
            <div className="relative">
              <input
                type={showApiKey ? "text" : "password"}
                value={customApiKey}
                onChange={(e) => setCustomApiKey(e.target.value)}
                placeholder={t("apiKeyPlaceholder")}
                className="w-full px-4 py-3 pr-20 rounded-lg border border-border/40 bg-background/50 text-text-primary placeholder:text-text-sub/40 focus:outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/20 transition-all"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1.5 text-xs font-medium text-text-sub/60 hover:text-primary transition-colors"
              >
                {showApiKey ? t("hideApiKey") : t("showApiKey")}
              </button>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border/40 bg-background/50 flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-border/40 text-text-sub hover:text-text-primary hover:border-border/60 transition-colors"
          >
            {t("cancel")}
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20"
          >
            {t("save")}
          </button>
        </div>
      </div>
    </div>
  );
}
