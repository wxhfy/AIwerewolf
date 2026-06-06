"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UseTypewriterOptions {
  charsPerSecond?: number;
  /** When false, the bubble is WAITING for its turn — show nothing.
   *  When true, animation starts (or continues from where it left off).
   *  Once finished, text persists even if enabled later becomes false. */
  enabled?: boolean;
  maxDurationMs?: number;
  /** Called once when the full text has finished revealing. */
  onComplete?: () => void;
}

interface UseTypewriterResult {
  displayedText: string;
  finished: boolean;
}

/**
 * Progressively reveals text.  The PARENT component serialises animations
 * via the `enabled` prop.
 *
 * Lifecycle:
 *  1. Mount with enabled=false → displayedText="" (waiting, shows cursor)
 *  2. enabled becomes true   → rAF animation starts from char 0
 *  3. Animation finishes     → onComplete fires, finished=true, text stays
 *  4. Parent sets enabled=false → text PERSISTS (no clearing on completion)
 *  5. fullText changes       → reset, go to step 1
 */
export function useTypewriter(
  fullText: string,
  options: UseTypewriterOptions = {},
): UseTypewriterResult {
  const { charsPerSecond = 35, enabled = false, maxDurationMs = 4000, onComplete } = options;

  const rafRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const [displayedText, setDisplayedText] = useState("");
  const [finished, setFinished] = useState(false);
  const completedRef = useRef(false);
  const lastFullTextRef = useRef(fullText);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete; // Always latest, never triggers re-render

  const shouldAnimate = useCallback(() => {
    if (!enabled) return false;
    if (fullText.length < 10) return false;
    if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    return true;
  }, [enabled, fullText]);

  useEffect(() => {
    const textChanged = lastFullTextRef.current !== fullText;
    if (textChanged) {
      lastFullTextRef.current = fullText;
      setDisplayedText("");
      setFinished(false);
      completedRef.current = false;
    }

    // Short text: show immediately regardless of enabled flag
    if (fullText.length > 0 && fullText.length < 10) {
      setDisplayedText(fullText);
      setFinished(true);
      if (!completedRef.current) {
        completedRef.current = true;
        onCompleteRef.current?.();
      }
      return;
    }

    // Already finished this text — persist it, don't restart
    if (completedRef.current) {
      setDisplayedText(fullText);
      setFinished(true);
      return;
    }

    // Not enabled yet — preserve whatever text was already displayed.
    // The parent controls enable/disable; clearing text here would
    // blank out bubbles that were externally completed (fallback timer,
    // phase timeout, or any other out-of-band completion).
    if (!enabled) {
      return;
    }

    // Enabled + not finished → start animating
    if (shouldAnimate()) {
      const effectiveCps = Math.max(charsPerSecond, fullText.length / (maxDurationMs / 1000));
      const msPerChar = 1000 / effectiveCps;
      startTimeRef.current = 0;
      let lastCharCount = 0;

      const tick = (timestamp: number) => {
        if (startTimeRef.current === 0) startTimeRef.current = timestamp;
        const elapsed = timestamp - startTimeRef.current;
        const charCount = Math.min(Math.floor(elapsed / msPerChar), fullText.length);

        if (charCount !== lastCharCount) {
          lastCharCount = charCount;
          setDisplayedText(fullText.slice(0, charCount));
        }

        if (charCount >= fullText.length) {
          setFinished(true);
          if (!completedRef.current) {
            completedRef.current = true;
            onCompleteRef.current?.();
          }
          return;
        }
        rafRef.current = requestAnimationFrame(tick);
      };

      rafRef.current = requestAnimationFrame(tick);

      return () => {
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
        }
      };
    }

    // enabled=true but text too short for animation → show immediately
    setDisplayedText(fullText);
    setFinished(true);
    if (!completedRef.current) {
      completedRef.current = true;
      onCompleteRef.current?.();
    }
  }, [fullText, shouldAnimate, charsPerSecond, maxDurationMs, enabled]);

  return { displayedText, finished };
}
