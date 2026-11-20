"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { EventType, GameEvent } from "@/types";
import { mergeConsecutiveChats, normalizeSpeechContent } from "@/lib/eventFilter";

export interface SpeechQueueItem {
  id: string;
  seq: number;
  actorId: string;
  actorName: string;
  actorSeat: number;
  fullText: string;
  displayedText: string;
  phase: string;
  day: number;
  isComplete: boolean;
}

interface UseSpeechQueueOptions {
  baseCharsPerSecond?: number;
  fastCharsPerSecond?: number;
  onSpeechComplete?: (eventId: string) => void;
}

export function useSpeechQueue(
  events: GameEvent[] | undefined,
  options: UseSpeechQueueOptions = {},
) {
  const {
    baseCharsPerSecond = 35,
    fastCharsPerSecond = 90,
    onSpeechComplete,
  } = options;

  const onSpeechCompleteRef = useRef(onSpeechComplete);
  onSpeechCompleteRef.current = onSpeechComplete;

  // Track event IDs that have already been queued or completed (dedupe against SSE replays)
  const seenIdsRef = useRef<Set<string>>(new Set());

  // Completed speeches displayed in the feed
  const [completedSpeeches, setCompletedSpeeches] = useState<SpeechQueueItem[]>([]);

  // Current speech item being typed out
  const [currentSpeech, setCurrentSpeech] = useState<SpeechQueueItem | null>(null);

  // Queue of speeches waiting to be typed
  const queueRef = useRef<SpeechQueueItem[]>([]);
  const [queueLength, setQueueLength] = useState(0);

  // Current typed text of currentSpeech
  const [typedText, setTypedText] = useState("");
  const typedTextRef = useRef("");
  typedTextRef.current = typedText;

  const rafRef = useRef<number | null>(null);
  const currentItemRef = useRef<SpeechQueueItem | null>(null);
  currentItemRef.current = currentSpeech;

  // Check prefers-reduced-motion
  const isReducedMotion = useCallback(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  // Finish typing the current item immediately
  const finishCurrentItem = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const item = currentItemRef.current;
    if (!item) return;

    const completedItem: SpeechQueueItem = {
      ...item,
      displayedText: item.fullText,
      isComplete: true,
    };

    setCompletedSpeeches((prev) => [...prev, completedItem]);
    setCurrentSpeech(null);
    setTypedText("");

    onSpeechCompleteRef.current?.(item.id);
  }, []);

  // Advance queue: if no current item and queue has items, start the next one
  const advanceQueue = useCallback(() => {
    if (currentItemRef.current !== null) return;
    if (queueRef.current.length === 0) {
      setQueueLength(0);
      return;
    }

    const nextItem = queueRef.current.shift()!;
    setQueueLength(queueRef.current.length);

    if (isReducedMotion() || nextItem.fullText.length < 5) {
      // Reduced motion or short speech: complete immediately
      const completed: SpeechQueueItem = {
        ...nextItem,
        displayedText: nextItem.fullText,
        isComplete: true,
      };
      setCompletedSpeeches((prev) => [...prev, completed]);
      onSpeechCompleteRef.current?.(nextItem.id);
      // Immediately schedule next check
      setTimeout(advanceQueue, 0);
      return;
    }

    setCurrentSpeech(nextItem);
    setTypedText("");
  }, [isReducedMotion]);

  // When events change, scan for new CHAT_MESSAGE events and queue them
  useEffect(() => {
    if (!events || events.length === 0) return;

    const merged = mergeConsecutiveChats(events);
    let addedCount = 0;

    for (const event of merged) {
      if (event.type !== EventType.CHAT_MESSAGE) continue;
      const eventId = event.id;
      if (!eventId || seenIdsRef.current.has(eventId)) continue;

      seenIdsRef.current.add(eventId);

      const p = event.payload || {};
      const speechRaw = p.speech || (p as any).message || "";
      const fullText = normalizeSpeechContent(speechRaw, "发言完毕，过。");
      const actorId = p.actor_id || (p as any).player_id || "";
      const actorName = p.actor_name || (p as any).player_name || "玩家";
      const actorSeat = Number((p as any).seat || (p as any).actor_seat || 0);

      const item: SpeechQueueItem = {
        id: eventId,
        seq: event.seq || 0,
        actorId,
        actorName,
        actorSeat,
        fullText,
        displayedText: "",
        phase: event.phase || "",
        day: event.day || 1,
        isComplete: false,
      };

      queueRef.current.push(item);
      addedCount++;
    }

    if (addedCount > 0) {
      setQueueLength(queueRef.current.length);
      advanceQueue();
    }
  }, [events, advanceQueue]);

  // Typewriter effect for currentSpeech
  useEffect(() => {
    if (!currentSpeech) {
      advanceQueue();
      return;
    }

    const fullText = currentSpeech.fullText;
    const pendingCount = queueRef.current.length;

    // Accelerate if queue length > 3
    const cps = pendingCount > 3 ? fastCharsPerSecond : baseCharsPerSecond;
    const msPerChar = 1000 / cps;

    let startTime = 0;
    let lastCharCount = 0;

    const tick = (timestamp: number) => {
      if (startTime === 0) startTime = timestamp;
      const elapsed = timestamp - startTime;
      const charCount = Math.min(Math.floor(elapsed / msPerChar), fullText.length);

      if (charCount !== lastCharCount) {
        lastCharCount = charCount;
        setTypedText(fullText.slice(0, charCount));
      }

      if (charCount >= fullText.length) {
        finishCurrentItem();
        return;
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [currentSpeech, baseCharsPerSecond, fastCharsPerSecond, finishCurrentItem, advanceQueue]);

  // All speeches to be displayed in the UI: completed speeches + currently typing speech
  const displayedSpeeches: SpeechQueueItem[] = [
    ...completedSpeeches,
    ...(currentSpeech ? [{ ...currentSpeech, displayedText: typedText }] : []),
  ];

  return {
    displayedSpeeches,
    currentSpeech: currentSpeech ? { ...currentSpeech, displayedText: typedText } : null,
    isTyping: currentSpeech !== null,
    queueLength,
    skipCurrent: finishCurrentItem,
    completedSpeeches,
  };
}
