"use client";

import { useEffect } from "react";
import { useAppContext } from "@/context/AppContext";

export function HtmlLang() {
  const { language } = useAppContext();

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  return null;
}
