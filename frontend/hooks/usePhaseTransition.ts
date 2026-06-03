"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { getPhaseGroup, PhaseGroup } from "@/lib/gamePhase";
import type { GameState } from "@/types";
import type { BlinkPhase } from "@/components/game/DayNightBlinkTransition";

export type VisualPhaseGroup = "day" | "night" | "end";
export type PhaseAnnouncementGroup = VisualPhaseGroup | "ready";

export interface PhaseAnnouncementState {
  group: PhaseAnnouncementGroup;
  visible: boolean;
}

/**
 * 昼夜转场中央协调器。
 *
 * 职责：
 * 1. 检测 day↔night 阶段变化
 * 2. 驱动眨眼动画状态机（BlinkPhase）
 * 3. 转场期间冻结前端可见事件流（displayGameState 不变）
 * 4. 缓冲转场期间到达的 WebSocket 快照
 * 5. 动画结束后对齐最新状态并恢复事件流
 */
export function usePhaseTransition(
  sessionKey: string,
  gameState: GameState | null,
  hasWinner: boolean,
) {
  // ── Phase state ─────────────────────────────────────────────────
  const [visualPhaseGroup, setVisualPhaseGroup] = useState<VisualPhaseGroup>("day");
  const [phaseAnnouncement, setPhaseAnnouncement] = useState<PhaseAnnouncementState | null>(null);

  // ── Blink animation state ───────────────────────────────────────
  const [isBlinking, setIsBlinking] = useState(false);
  const [blinkPhase, setBlinkPhase] = useState<BlinkPhase>(null);

  // ── Event flow freeze / buffer ──────────────────────────────────
  // 眨眼开始时捕获的冻结状态（UI 在整个转场期间展示这个状态）
  const frozenStateRef = useRef<GameState | null>(null);
  // 眨眼期间 WebSocket 推送的最新快照（只保留最新一份）
  const pendingStateRef = useRef<GameState | null>(null);
  // 暴露给外部：isBlinking 的最新值（避免闭包过期）
  const isBlinkingRef = useRef(false);

  // ── Internal refs ───────────────────────────────────────────────
  const lastPhaseGroupRef = useRef<PhaseGroup>("other");
  const hasHandledFirstPhaseRef = useRef(false);
  const transitionTokenRef = useRef(0);
  const transitionTimersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const lastSessionKeyRef = useRef("");
  const handledEndSessionKeyRef = useRef<string | null>(null);
  const targetPhaseRef = useRef<"day" | "night">("day");
  const announceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 同步 ref
  useEffect(() => { isBlinkingRef.current = isBlinking; }, [isBlinking]);

  // ── Helpers ──────────────────────────────────────────────────────

  function cancelPhaseTransition() {
    transitionTokenRef.current += 1;
    for (const timer of transitionTimersRef.current) clearTimeout(timer);
    transitionTimersRef.current = [];
    if (announceTimerRef.current) clearTimeout(announceTimerRef.current);
    announceTimerRef.current = null;
  }

  function clearAnnouncement() {
    announceTimerRef.current = setTimeout(() => {
      setPhaseAnnouncement((current) => current ? { ...current, visible: false } : null);
      announceTimerRef.current = setTimeout(() => {
        setPhaseAnnouncement(null);
        announceTimerRef.current = null;
      }, 400);
    }, 1200);
  }

  // ── Snapshot buffering (called by useRoomStream during blink) ────

  /** 眨眼期间缓存 WebSocket 快照，只保留最新一份 */
  const bufferSnapshot = useCallback((state: GameState) => {
    pendingStateRef.current = state;
  }, []);

  /** 检查是否正在眨眼（供 useRoomStream 使用，ref 避免闭包过期） */
  const getIsBlinking = useCallback(() => isBlinkingRef.current, []);

  // ── Blink 动画回调 ──────────────────────────────────────────────

  /** 闭眼动画完成 → 切换底层背景 → 进入全黑停顿 */
  const handleBlinkCloseComplete = useCallback(() => {
    const target = targetPhaseRef.current;
    setVisualPhaseGroup(target);
    setBlinkPhase("paused");
  }, []);

  /** 全黑停顿完成 → 决定下一步动作 */
  const handleBlinkPauseComplete = useCallback(() => {
    const target = targetPhaseRef.current;
    if (target === "day") {
      // night → day：打开眼皮露出白天
      setBlinkPhase("opening");
    } else {
      // day → night：保持黑暗，显示 "天黑请闭眼"
      _finishBlink("night");
    }
  }, []);

  /** 睁眼动画完成 → 恢复交互，对齐最新状态，显示 "天亮了" */
  const handleBlinkOpenComplete = useCallback(() => {
    _finishBlink("day");
  }, []);

  /**
   * 结束眨眼转场：刷新 buffer，对齐最新状态。
   * 返回对齐后的最新 GameState（可能为 null）。
   */
  function _finishBlink(announcementGroup: "day" | "night") {
    setBlinkPhase(null);
    setIsBlinking(false);

    // 释放冻结
    frozenStateRef.current = null;

    // 取出缓冲的最新快照
    const pending = pendingStateRef.current;
    pendingStateRef.current = null;

    // 通过 ref 标记：useRoomStream 的下一个 snapshot 或 flush 来的 pending
    // 需要通知 controller 应用最新状态
    // 我们把 pending 通过一个公开的 ref 传出去，让 controller 在回调中读取
    flushResultRef.current = pending;

    // 只在非游戏结束时显示阶段公告
    if (pending && pending.winner) {
      // 游戏在转场期间结束 → 不显示阶段公告，直接让 controller 展示结算
      return;
    }

    setPhaseAnnouncement({ group: announcementGroup, visible: true });
    clearAnnouncement();
  }

  // 暴露给 controller：flush 后待应用的最新 state
  const flushResultRef = useRef<GameState | null>(null);

  // ── 简化版转场（prefers-reduced-motion） ──────────────────────

  function simpleTransition(next: "day" | "night") {
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;

    setPhaseAnnouncement({ group: next, visible: true });
    const switchTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setVisualPhaseGroup(next);
    }, 400);
    const fadeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token)
        setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
    }, 1200);
    const removeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
    }, 1600);
    transitionTimersRef.current = [switchTimer, fadeTimer, removeTimer];
  }

  // ── Framer Motion 眨眼转场（主流程） ─────────────────────────────

  function startBlinkTransition(next: "day" | "night") {
    cancelPhaseTransition();

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      simpleTransition(next);
      return;
    }

    // 冻结当前状态：UI 在整个转场期间都展示这个状态
    frozenStateRef.current = gameState;
    // 清空 buffer，准备接收转场期间的新快照
    pendingStateRef.current = null;
    flushResultRef.current = null;
    targetPhaseRef.current = next;

    setIsBlinking(true);
    setBlinkPhase("closing");
    // 后续由 handleBlinkCloseComplete → handleBlinkPauseComplete →
    // handleBlinkOpenComplete / _finishBlink 链式驱动
  }

  // ── 首次入场（游戏开始可能是夜晚） ──────────────────────────────

  function startFirstNightTransition() {
    cancelPhaseTransition();
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      const token = ++transitionTokenRef.current;
      setPhaseAnnouncement({ group: "ready", visible: true });
      const readyFade = setTimeout(() => {
        if (transitionTokenRef.current === token)
          setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
      }, 800);
      const showNight = setTimeout(() => {
        if (transitionTokenRef.current === token)
          setPhaseAnnouncement({ group: "night", visible: true });
      }, 1100);
      const switchTheme = setTimeout(() => {
        if (transitionTokenRef.current === token) setVisualPhaseGroup("night");
      }, 1500);
      const fade = setTimeout(() => {
        if (transitionTokenRef.current === token)
          setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
      }, 2700);
      const remove = setTimeout(() => {
        if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
      }, 3100);
      transitionTimersRef.current = [readyFade, showNight, switchTheme, fade, remove];
      return;
    }

    // 短暂显示 "准备" → 闭眼 → 切换夜晚
    setPhaseAnnouncement({ group: "ready", visible: true });
    const readyFade = setTimeout(() => {
      setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
      announceTimerRef.current = setTimeout(() => {
        setPhaseAnnouncement(null);
        // 开始闭眼
        frozenStateRef.current = gameState;
        pendingStateRef.current = null;
        flushResultRef.current = null;
        targetPhaseRef.current = "night";
        setIsBlinking(true);
        setBlinkPhase("closing");
      }, 400);
    }, 800);
    transitionTimersRef.current = [readyFade];
  }

  // ── 游戏结束 ────────────────────────────────────────────────────

  function enterEndPhase() {
    if (
      handledEndSessionKeyRef.current === sessionKey &&
      lastPhaseGroupRef.current === "end"
    )
      return;
    handledEndSessionKeyRef.current = sessionKey;
    cancelPhaseTransition();
    setBlinkPhase(null);
    setIsBlinking(false);
    frozenStateRef.current = null;
    pendingStateRef.current = null;
    setVisualPhaseGroup("end");
    setPhaseAnnouncement({ group: "end", visible: true });
    lastPhaseGroupRef.current = "end";

    const fadeTimer = setTimeout(() => {
      setPhaseAnnouncement((current) =>
        current ? { ...current, visible: false } : null,
      );
    }, 1100);
    const removeTimer = setTimeout(() => {
      setPhaseAnnouncement(null);
    }, 1400);
    transitionTimersRef.current = [fadeTimer, removeTimer];
  }

  // ── data-phase 属性同步 ─────────────────────────────────────────

  useLayoutEffect(() => {
    document.documentElement.setAttribute("data-phase", visualPhaseGroup);
  }, [visualPhaseGroup]);

  useEffect(() => {
    return () => {
      cancelPhaseTransition();
      document.documentElement.setAttribute("data-phase", "day");
    };
  }, []);

  // ── 阶段变化检测 ────────────────────────────────────────────────

  useEffect(() => {
    // 新房间：重置所有状态
    if (lastSessionKeyRef.current !== sessionKey) {
      cancelPhaseTransition();
      setPhaseAnnouncement(null);
      setBlinkPhase(null);
      setIsBlinking(false);
      frozenStateRef.current = null;
      pendingStateRef.current = null;
      flushResultRef.current = null;
      lastPhaseGroupRef.current = "other";
      hasHandledFirstPhaseRef.current = false;
      handledEndSessionKeyRef.current = null;
      setVisualPhaseGroup("day");
      lastSessionKeyRef.current = sessionKey;
    }

    const phase = gameState?.phase;
    const nextGroup = hasWinner ? "end" : getPhaseGroup(phase);
    if (nextGroup === "other") return;

    // 游戏结束
    if (nextGroup === "end") {
      enterEndPhase();
      return;
    }

    // 首次阶段变化处理
    if (!hasHandledFirstPhaseRef.current) {
      hasHandledFirstPhaseRef.current = true;
      lastPhaseGroupRef.current = nextGroup;
      if (nextGroup === "night") {
        startFirstNightTransition();
      } else {
        setVisualPhaseGroup("day");
      }
      return;
    }

    // 正常昼夜切换
    const prevGroup = lastPhaseGroupRef.current;
    if (
      (prevGroup === "day" || prevGroup === "night") &&
      nextGroup !== prevGroup
    ) {
      lastPhaseGroupRef.current = nextGroup;
      startBlinkTransition(nextGroup as "day" | "night");
      return;
    }

    lastPhaseGroupRef.current = nextGroup;
    if (prevGroup === "other" || prevGroup === "end")
      setVisualPhaseGroup(nextGroup as VisualPhaseGroup);
  }, [sessionKey, gameState?.phase, hasWinner]);

  // ── Effective display state ──────────────────────────────────────
  // 眨眼期间返回冻结的旧状态，UI 不会看到新事件
  // 眨眼结束后返回实际 gameState（已在 _finishBlink 中通过 flushResultRef 通知 controller 更新）

  const displayGameState: GameState | null =
    isBlinking && frozenStateRef.current ? frozenStateRef.current : gameState;

  return {
    visualPhaseGroup,
    isVisualNight: visualPhaseGroup === "night",
    phaseAnnouncement,
    // Blink state
    isBlinking,
    blinkPhase,
    // Event flow control
    displayGameState,
    bufferSnapshot,
    getIsBlinking,
    flushResultRef,
    // Blink callbacks (for DayNightBlinkTransition)
    onBlinkCloseComplete: handleBlinkCloseComplete,
    onBlinkPauseComplete: handleBlinkPauseComplete,
    onBlinkOpenComplete: handleBlinkOpenComplete,
  };
}
