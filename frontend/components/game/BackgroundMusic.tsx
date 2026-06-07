"use client";

import React, { useEffect, useRef, useState } from "react";
import { Language } from "@/types";

interface BackgroundMusicProps {
  language: Language;
}

export function BackgroundMusic({ language }: BackgroundMusicProps) {
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

  return (
    <>
      <audio ref={audioRef} src="/audio/werewolf-bgm.ogg" preload="auto" />
      <button
        type="button"
        onClick={() => setEnabled((value) => !value)}
        className="fixed bottom-4 right-4 z-[80] rounded-full border border-border bg-cardBackground/85 px-3 py-2 text-xs font-medium text-textPrimary shadow-float backdrop-blur transition hover:border-primary/50"
        title={language === Language.ZH ? "背景音乐" : "Background music"}
      >
        {enabled
          ? started
            ? language === Language.ZH ? "音乐开" : "Music On"
            : language === Language.ZH ? "点击播音乐" : "Start Music"
          : language === Language.ZH ? "音乐关" : "Music Off"}
      </button>
    </>
  );
}
