"use client";

import React, { useState, useEffect, useRef } from "react";

interface CountdownTimerProps {
  seconds: number;
  onExpire: () => void;
  isActive: boolean;
}

export function CountdownTimer({ seconds, onExpire, isActive }: CountdownTimerProps) {
  const [remaining, setRemaining] = useState(seconds);
  const expiredRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!isActive) {
      setRemaining(seconds);
      expiredRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }
    setRemaining(seconds);
    expiredRef.current = false;
    intervalRef.current = setInterval(() => {
      setRemaining((prev) => {
        const next = prev - 0.25;
        if (next <= 0 && !expiredRef.current) {
          expiredRef.current = true;
          setTimeout(onExpire, 0);
          return 0;
        }
        return next <= 0 ? 0 : next;
      });
    }, 250);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isActive, seconds, onExpire]);

  const pct = Math.max(0, (remaining / seconds) * 100);
  const isWarn = remaining <= 20 && remaining > 10;
  const isDanger = remaining <= 10;

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: "var(--color-border)" }}>
        <div
          className="h-full rounded-full transition-all duration-200"
          style={{
            width: `${pct}%`,
            backgroundColor: isDanger ? "#B91C1C" : isWarn ? "#D97706" : "var(--color-primary)",
            transition: "width 250ms linear, background-color 300ms ease",
          }}
        />
      </div>
      <span className={`text-xs font-mono min-w-[36px] text-right tabular-nums ${
        isDanger ? "text-danger font-bold animate-pulse-loading" : isWarn ? "text-[#D97706] font-semibold" : "text-text-sub"
      }`}>
        {Math.ceil(remaining)}s
      </span>
    </div>
  );
}
