"use client";

import React, { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

interface CountdownTimerProps {
  seconds: number;
  onExpire: () => void;
  isActive: boolean;
}

export function CountdownTimer({ seconds, onExpire, isActive }: CountdownTimerProps) {
  const [remaining, setRemaining] = useState(seconds);
  const expiredRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;  // Always current, never triggers re-render

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
        return next <= 0 ? 0 : next;
      });
      if (remaining <= 0.5 && !expiredRef.current) {
        expiredRef.current = true;
        setTimeout(() => onExpireRef.current(), 0);
      }
    }, 250);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isActive, seconds]);

  const pct = Math.max(0, (remaining / seconds) * 100);
  const isWarn = remaining <= 20 && remaining > 10;
  const isDanger = remaining <= 10;

  return (
    <div className="flex items-center gap-2" role="timer" aria-label={`${Math.ceil(remaining)} seconds remaining`}>
      <div className="flex-1 h-2 rounded-full overflow-hidden bg-border" role="progressbar" aria-valuenow={Math.ceil(remaining)} aria-valuemin={0} aria-valuemax={seconds}>
        <div
          className={cn(
            "h-full rounded-full transition-all duration-200",
            isDanger ? "bg-danger" : isWarn ? "bg-warning" : "bg-primary"
          )}
          style={{
            width: `${pct}%`,
            transition: "width 250ms linear, background-color 300ms ease",
          }}
        />
      </div>
      <span
        className={cn(
          "text-xs font-mono min-w-[36px] text-right tabular-nums",
          isDanger
            ? "text-danger font-bold animate-pulse-loading"
            : isWarn
              ? "text-warning font-semibold"
              : "text-text-sub"
        )}
      >
        {Math.ceil(remaining)}s
      </span>
    </div>
  );
}
