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

// ── 时序常量 ───────────────────────────────────────────────────────
// 阶段公告显示时长（毫秒），闭眼/睁眼前用户阅读文字的时间
const ANNOUNCE_DISPLAY_MS = 1200;
// 公告淡出时长
const ANNOUNCE_FADE_MS = 400;
// 全黑停顿
const PAUSE_DURATION_MS = 150;

/**
 * 昼夜转场中央协调器 — v2。
 *
 * 正确的动画时序：
 *   Day→Night: 先显示"天黑请闭眼" → 闭眼动画 → 全黑停顿 → 切换夜晚
 *   Night→Day: 先显示"天亮了" → 眨眼动画(闭→停→睁) → 切换白天
 *
 * 转场期间：
 *  - transitioning=true 锁住 UI，防止组件抢状态
 *  - displayGameState 返回冻结的旧状态
 *  - WebSocket 快照缓冲到 pendingStateRef
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

  // ── Transitioning lock ──────────────────────────────────────────
  // true = 转场进行中（从触发到 _finishBlink 完成），UI 组件可用此锁暂停更新
  const [isTransitioning, setIsTransitioning] = useState(false);

  // ── Event flow freeze / buffer ──────────────────────────────────
  const frozenStateRef = useRef<GameState | null>(null);
  const pendingStateRef = useRef<GameState | null>(null);
  const isBlinkingRef = useRef(false);
  const isTransitioningRef = useRef(false);

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
  useEffect(() => { isTransitioningRef.current = isTransitioning; }, [isTransitioning]);

  // ── Helpers ──────────────────────────────────────────────────────

  function cancelPhaseTransition() {
    transitionTokenRef.current += 1;
    for (const timer of transitionTimersRef.current) clearTimeout(timer);
    transitionTimersRef.current = [];
    if (announceTimerRef.current) clearTimeout(announceTimerRef.current);
    announceTimerRef.current = null;
  }

  /** 设置阶段公告并在 delay 后自动淡出 */
  function showAnnouncement(
    group: PhaseAnnouncementGroup,
    displayMs: number,
    token: number,
  ): void {
    setPhaseAnnouncement({ group, visible: true });
    const fadeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token)
        setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
    }, displayMs);
    const removeTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) setPhaseAnnouncement(null);
    }, displayMs + ANNOUNCE_FADE_MS);
    transitionTimersRef.current.push(fadeTimer, removeTimer);
  }

  // ── Snapshot buffering ───────────────────────────────────────────

  const bufferSnapshot = useCallback((state: GameState) => {
    pendingStateRef.current = state;
  }, []);

  const getIsBlinking = useCallback(() => isBlinkingRef.current, []);

  // ── Blink 动画回调 ──────────────────────────────────────────────

  /** 闭眼动画完成 → 切换底层视觉 → 进入全黑停顿 */
  const handleBlinkCloseComplete = useCallback(() => {
    const target = targetPhaseRef.current;
    setVisualPhaseGroup(target);
    setBlinkPhase("paused");
  }, []);

  /** 全黑停顿完成 → 决定下一步 */
  const handleBlinkPauseComplete = useCallback(() => {
    const target = targetPhaseRef.current;
    if (target === "day") {
      // night→day：停顿后睁眼
      setBlinkPhase("opening");
    } else {
      // day→night：停顿后完成（保持黑暗）
      _finishBlink("night");
    }
  }, []);

  /** 睁眼动画完成 → 完成转场 */
  const handleBlinkOpenComplete = useCallback(() => {
    _finishBlink("day");
  }, []);

  /**
   * 结束眨眼转场：blink 动画完成后进入 settling 期。
   *
   * settling 期（~1s）：
   *  - isBlinking = false（眼皮已移开）
   *  - isTransitioning = true（锁住 UI + 阻止事件 flush）
   *
   * ⚠️ 此阶段不再重复显示"天黑请闭眼"/"天亮了"公告 —
   *   公告已在 startBlinkTransition / startFirstNightTransition 中先行显示，
   *   眨眼动画本身（黑屏/亮屏）已充分传达昼夜切换信息。
   *
   * settling 结束后释放 transition 锁并 flush 缓冲事件，确保：
   *  - 页面背景完全变黑后，"守卫请睁眼"才出现
   *  - 玩家卡片高亮和角色日志同步
   */
  function _finishBlink(_announcementGroup: "day" | "night") {
    setBlinkPhase(null);
    setIsBlinking(false);
    // ⚠️ 保持 isTransitioning = true，由 settling timer 释放

    frozenStateRef.current = null;

    // 检查缓冲状态中是否游戏已结束
    const pending = pendingStateRef.current;
    if (pending && pending.winner) {
      // 游戏结束 → 立即释放，不作 settling；enterEndPhase 负责公告
      pendingStateRef.current = null;
      flushResultRef.current = pending;
      setIsTransitioning(false);
      // 不在此设置 phaseAnnouncement — enterEndPhase 会在状态更新后统一处理
      return;
    }

    // ── settling: 静默缓冲，眨眼动画本身已传达昼夜信息 ──
    const SETTLE_MS = _announcementGroup === "night" ? 1000 : 500;

    // settling 结束后：释放 transition 锁 → flush 事件
    const releaseTimer = setTimeout(() => {
      setIsTransitioning(false);
      const p = pendingStateRef.current;
      pendingStateRef.current = null;
      flushResultRef.current = p;
    }, SETTLE_MS + 100);

    transitionTimersRef.current = [releaseTimer];
  }

  const flushResultRef = useRef<GameState | null>(null);

  // ── prefers-reduced-motion 简化转场 ────────────────────────────

  function simpleTransition(next: "day" | "night") {
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;

    setIsTransitioning(true);
    showAnnouncement(next, ANNOUNCE_DISPLAY_MS, token);

    const switchTimer = setTimeout(() => {
      if (transitionTokenRef.current === token) {
        setVisualPhaseGroup(next);
        setIsTransitioning(false);
      }
    }, ANNOUNCE_DISPLAY_MS + ANNOUNCE_FADE_MS);
    transitionTimersRef.current.push(switchTimer);
  }

  // ── Framer Motion 眨眼转场（主流程 v2）──────────────────────────

  /**
   * Day→Night 转场：
   *   1. 显示"天黑请闭眼"公告
   *   2. 公告淡出 → 闭眼动画 → 全黑停顿 → 完成
   *
   * Night→Day 转场：
   *   1. 显示"天亮了"公告
   *   2. 公告淡出 → 眨眼动画(闭→停→睁) → 完成
   */
  function startBlinkTransition(next: "day" | "night") {
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      simpleTransition(next);
      return;
    }

    // ── 1. 冻结状态 + 锁 UI ──
    frozenStateRef.current = gameState;
    pendingStateRef.current = null;
    flushResultRef.current = null;
    targetPhaseRef.current = next;
    setIsTransitioning(true);

    // ── 2. 先显示阶段公告（文字先行） ──
    const announceGroup: PhaseAnnouncementGroup = next;
    setPhaseAnnouncement({ group: announceGroup, visible: true });

    // 公告显示 ANNOUNCE_DISPLAY_MS 后淡出，然后开始眨眼动画
    const announceFadeTimer = setTimeout(() => {
      if (transitionTokenRef.current !== token) return;
      setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
    }, ANNOUNCE_DISPLAY_MS);

    // 公告移除 + 开始眨眼动画
    const startBlinkTimer = setTimeout(() => {
      if (transitionTokenRef.current !== token) return;
      setPhaseAnnouncement(null);
      // ── 3. 开始眨眼动画 ──
      setIsBlinking(true);
      setBlinkPhase("closing");
      // 后续链式驱动: handleBlinkCloseComplete → handleBlinkPauseComplete →
      //   → (day: 睁眼 → handleBlinkOpenComplete → _finishBlink)
      //   → (night: _finishBlink)
    }, ANNOUNCE_DISPLAY_MS + ANNOUNCE_FADE_MS);

    transitionTimersRef.current = [announceFadeTimer, startBlinkTimer];
  }

  // ── 首次入场（游戏从准备→第一夜）────────────────────────────────

  function startFirstNightTransition() {
    cancelPhaseTransition();
    const token = ++transitionTokenRef.current;

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      setIsTransitioning(true);
      showAnnouncement("ready", 800, token);
      const showNightTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) {
          showAnnouncement("night", ANNOUNCE_DISPLAY_MS, token);
        }
      }, 1200);
      const switchTimer = setTimeout(() => {
        if (transitionTokenRef.current === token) {
          setVisualPhaseGroup("night");
          setIsTransitioning(false);
        }
      }, 1200 + ANNOUNCE_DISPLAY_MS + ANNOUNCE_FADE_MS);
      transitionTimersRef.current.push(showNightTimer, switchTimer);
      return;
    }

    // ── 完整流程：冻结状态 → 准备公告 → 天黑请闭眼公告 → 闭眼动画 → 夜晚 ──
    // ⚠️ 必须第一时间冻结，否则 displayGameState 在公告期间返回实时 gameState，
    // 后端推进到守卫阶段后"守卫请睁眼"会在天黑前就渲染出来。
    frozenStateRef.current = gameState;
    pendingStateRef.current = null;
    flushResultRef.current = null;
    targetPhaseRef.current = "night";
    setIsTransitioning(true);

    // 1. 显示"身份已分配，对局即将开始"
    showAnnouncement("ready", 1000, token);

    // 2. 之后显示"天黑请闭眼" → 闭眼动画
    const nightAnnounceTimer = setTimeout(() => {
      if (transitionTokenRef.current !== token) return;
      // 显示天黑请闭眼
      setPhaseAnnouncement({ group: "night", visible: true });

      const fadeTimer = setTimeout(() => {
        if (transitionTokenRef.current !== token) return;
        setPhaseAnnouncement((c) => (c ? { ...c, visible: false } : null));
      }, ANNOUNCE_DISPLAY_MS);

      const blinkTimer = setTimeout(() => {
        if (transitionTokenRef.current !== token) return;
        setPhaseAnnouncement(null);

        // 3. 开始闭眼动画（状态已在函数开头冻结，此处不再重复）
        setIsBlinking(true);
        setBlinkPhase("closing");
      }, ANNOUNCE_DISPLAY_MS + ANNOUNCE_FADE_MS);

      transitionTimersRef.current.push(fadeTimer, blinkTimer);
    }, 1400);

    transitionTimersRef.current.push(nightAnnounceTimer);
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
    setIsTransitioning(false);
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
      setIsTransitioning(false);
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
  // 转场期间返回冻结状态，防止 UI 看到过渡期数据

  const displayGameState: GameState | null =
    (isBlinking || isTransitioning) && frozenStateRef.current
      ? frozenStateRef.current
      : gameState;

  return {
    visualPhaseGroup,
    isVisualNight: visualPhaseGroup === "night",
    phaseAnnouncement,
    // Blink state
    isBlinking,
    blinkPhase,
    // Transitioning lock
    isTransitioning,
    // Event flow control
    displayGameState,
    bufferSnapshot,
    getIsBlinking,
    flushResultRef,
    // Blink callbacks
    onBlinkCloseComplete: handleBlinkCloseComplete,
    onBlinkPauseComplete: handleBlinkPauseComplete,
    onBlinkOpenComplete: handleBlinkOpenComplete,
  };
}
