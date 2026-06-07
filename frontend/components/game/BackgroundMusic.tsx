"use client";

import React, { useEffect, useRef, useState } from "react";
import { Language } from "@/types";
import { cn } from "@/lib/utils";

interface BackgroundMusicProps {
  language: Language;
  placement?: "top-right" | "bottom-right";
}

function MusicOnIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 18V5l12-2v13" />
      <circle cx="6" cy="18" r="3" />
      <circle cx="18" cy="16" r="3" />
    </svg>
  );
}

function MusicOffIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 18V5l12-2v9" />
      <circle cx="6" cy="18" r="3" />
      <path d="m16 16 5 5" />
      <path d="m21 16-5 5" />
      <path d="M3 3l18 18" />
    </svg>
  );
}

export function BackgroundMusic({ language, placement = "top-right" }: BackgroundMusicProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = 0.32;
    audio.loop = true;

    const tryPlay = () => {
      if (!enabled) return;
      void audio.play().then(() => setStarted(true)).catch(() => {
        setStarted(false);
      });
    };

    tryPlay();
    const events = ["pointerdown", "keydown", "touchstart"];
    events.forEach((eventName) => window.addEventListener(eventName, tryPlay, { once: true }));
    return () => {
      events.forEach((eventName) => window.removeEventListener(eventName, tryPlay));
    };
  }, [enabled]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (enabled) {
      void audio.play().then(() => setStarted(true)).catch(() => setStarted(false));
    } else {
      audio.pause();
      setStarted(false);
    }
  }, [enabled]);

  const label = enabled
    ? started
      ? language === Language.ZH ? "背景音乐已开启" : "Background music on"
      : language === Language.ZH ? "点击播放背景音乐" : "Start background music"
    : language === Language.ZH ? "背景音乐已关闭" : "Background music off";

  return (
    <>
      <audio ref={audioRef} src="/audio/werewolf-bgm.ogg" preload="auto" />
      <button
        type="button"
        onClick={() => setEnabled((value) => !value)}
        className={cn(
          "fixed z-[80] flex h-10 w-10 items-center justify-center rounded-full border border-border bg-cardBackground/85 text-textPrimary shadow-float backdrop-blur transition hover:border-primary/50 hover:text-primary",
          placement === "top-right" ? "right-4 top-4" : "bottom-4 right-4",
          enabled && started && "border-primary/40 text-primary",
        )}
        title={label}
        aria-label={label}
      >
        {enabled ? <MusicOnIcon /> : <MusicOffIcon />}
      </button>
    </>
  );
}
