"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { getPhaseGroup, PhaseGroup } from "@/lib/gamePhase";

export type VisualPhaseGroup = "day" | "night" | "end";
export type PhaseAnnouncementGroup = VisualPhaseGroup | "ready";

export interface PhaseAnnouncementState {
  group: PhaseAnnouncementGroup;
  visible: boolean;
}

export function usePhaseTransition(sessionKey: string, phase?: string, hasWinner = false) {
  const [visualPhaseGroup, setVisualPhaseGroup] = useState<VisualPhaseGroup>("day");
  const [phaseAnnouncement, setPhaseAnnouncement] = useState<PhaseAnnouncementState | null>(null);
  const lastPhaseGroupRef = useRef<PhaseGroup>("other");
  const hasHandledFirstPhaseRef = useRef(false);
  const transitionTokenRef = useRef(0);
  const transitionTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const lastSessionKeyRef = useRef("");
  const handledEndSessionKeyRef = useRef<string | null>(null);

  function cancelPhaseTransition() {
    transitionTokenRef.current += 1;
    for (const timer of transitionTimersRef.current) clearTimeout(timer);
    transitionTimersRef.current = [];
  }

  function startVisualPhaseTransition(next: "day" | "night", options?: { openingBuffer?: boolean }) {
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;
    const reduceMotion = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const announcementGroup: PhaseAnnouncementGroup = options?.openingBuffer ? "ready" : next;

    if (reduceMotion) {
      setPhaseAnnouncement({ group: announcementGroup, visible: true });

      if (options?.openingBuffer) {
        const nightAnnouncementTimer = setTimeout(() => {
          if (transitionTokenRef.current === token) {
            setPhaseAnnouncement({ group: next, visible: true });
            setVisualPhaseGroup(next);
          }
        }, 120);
        const fadeTimer = setTimeout(() => {
          if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
        }, 520);
        const removeTimer = setTimeout(() => {
          if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
        }, 820);
        transitionTimersRef.current = [nightAnnouncementTimer, fadeTimer, removeTimer];
        return;
      }

      setVisualPhaseGroup(next);
      const fadeTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
      }, 400);
      const removeTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
      }, 700);
      transitionTimersRef.current = [fadeTimer, removeTimer];
      return;
    }

    setPhaseAnnouncement({ group: announcementGroup, visible: true });

    if (options?.openingBuffer) {
      const readyFadeTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
      }, 950);
      const nightAnnouncementTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement({ group: next, visible: true });
      }, 1200);
      const switchTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setVisualPhaseGroup(next);
      }, 1320);
      const fadeTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
      }, 2650);
      const removeTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
      }, 2950);
      transitionTimersRef.current = [readyFadeTimer, nightAnnouncementTimer, switchTimer, fadeTimer, removeTimer];
      return;
    }

    const switchTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setVisualPhaseGroup(next);
    }, 120);
    const fadeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
    }, 1450);
    const removeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
    }, 1750);
    transitionTimersRef.current = [switchTimer, fadeTimer, removeTimer];
  }

  function enterEndPhase() {
    if (handledEndSessionKeyRef.current === sessionKey && lastPhaseGroupRef.current === "end") return;

    handledEndSessionKeyRef.current = sessionKey;
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;
    setVisualPhaseGroup("end");
    setPhaseAnnouncement({ group: "end", visible: true });
    lastPhaseGroupRef.current = "end";

    const fadeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
    }, 1100);
    const removeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
    }, 1400);
    transitionTimersRef.current = [fadeTimer, removeTimer];
  }

  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-phase", visualPhaseGroup);
  }, [visualPhaseGroup]);

  useEffect(() => {
    return () => {
      cancelPhaseTransition();
      document.documentElement.setAttribute("data-phase", "day");
    };
  }, []);

  useEffect(() => {
    if (lastSessionKeyRef.current !== sessionKey) {
      cancelPhaseTransition();
      setPhaseAnnouncement(null);
      lastPhaseGroupRef.current = "other";
      hasHandledFirstPhaseRef.current = false;
      handledEndSessionKeyRef.current = null;
      setVisualPhaseGroup("day");
      lastSessionKeyRef.current = sessionKey;
    }

    const nextGroup = hasWinner ? "end" : getPhaseGroup(phase);
    if (nextGroup === "other") return;
    if (nextGroup === "end") {
      enterEndPhase();
      return;
    }

    if (!hasHandledFirstPhaseRef.current) {
      hasHandledFirstPhaseRef.current = true;
      lastPhaseGroupRef.current = nextGroup;
      if (nextGroup === "night") {
        startVisualPhaseTransition("night", { openingBuffer: true });
      } else {
        setVisualPhaseGroup("day");
      }
      return;
    }

    const prevGroup = lastPhaseGroupRef.current;
    if ((prevGroup === "day" || prevGroup === "night") && nextGroup !== prevGroup) {
      lastPhaseGroupRef.current = nextGroup;
      startVisualPhaseTransition(nextGroup);
      return;
    }

    lastPhaseGroupRef.current = nextGroup;
    if (prevGroup === "other" || prevGroup === "end") setVisualPhaseGroup(nextGroup);
  }, [sessionKey, phase, hasWinner]);

  return {
    visualPhaseGroup,
    isVisualNight: visualPhaseGroup === "night",
    phaseAnnouncement,
  };
}
