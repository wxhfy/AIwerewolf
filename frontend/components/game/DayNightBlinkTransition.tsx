"use client";

import { useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";

export type BlinkPhase = "closing" | "paused" | "opening" | null;

interface DayNightBlinkTransitionProps {
  blinkPhase: BlinkPhase;
  onCloseComplete?: () => void;
  onPauseComplete?: () => void;
  onOpenComplete?: () => void;
}

const PAUSE_DURATION = 150; // 全黑停顿 150ms

const eyelidEase: [number, number, number, number] = [0.76, 0, 0.24, 1]; // easeInOutQuart
const CLOSE_DURATION = 0.35; // 闭眼 350ms
const OPEN_DURATION = 0.45; // 睁眼 450ms

/**
 * 昼夜眨眼转场组件 — 模拟真人"闭眼/睁眼"效果。
 *
 * 闭眼：上眼皮从屏幕顶部向下滑动，下眼皮从底部向上滑动，
 *       中间可视区域逐渐变窄直到完全黑屏。
 * 睁眼：从中间先打开细缝，黑暗遮罩向上下两侧退开。
 *
 * 动画使用 Framer Motion 实现，遮罩层 z-index=1500 覆盖全页面。
 */
export function DayNightBlinkTransition({
  blinkPhase,
  onCloseComplete,
  onPauseComplete,
  onOpenComplete,
}: DayNightBlinkTransitionProps) {
  const pauseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completedRef = useRef<{ close: boolean; open: boolean; pause: boolean }>({
    close: false,
    open: false,
    pause: false,
  });
  const blinkPhaseRef = useRef(blinkPhase);
  blinkPhaseRef.current = blinkPhase;

  // 清理 timer
  useEffect(() => {
    return () => {
      if (pauseTimerRef.current) clearTimeout(pauseTimerRef.current);
    };
  }, []);

  // 管理 pause timer
  useEffect(() => {
    if (blinkPhase === "paused" && !completedRef.current.pause) {
      pauseTimerRef.current = setTimeout(() => {
        completedRef.current.pause = true;
        // 只有当前 blinkPhase 仍是 paused 时才触发
        if (blinkPhaseRef.current === "paused") {
          onPauseComplete?.();
        }
      }, PAUSE_DURATION);
    }
    if (blinkPhase !== "paused") {
      if (pauseTimerRef.current) clearTimeout(pauseTimerRef.current);
      completedRef.current.pause = false;
    }
    // 当 direction 改变时重置完成标记
    if (blinkPhase === "closing") completedRef.current.close = false;
    if (blinkPhase === "opening") completedRef.current.open = false;
  }, [blinkPhase, onPauseComplete]);

  const handleCloseComplete = useCallback(() => {
    if (completedRef.current.close) return; // 防止重复触发
    completedRef.current.close = true;
    // 确认当前 blinkPhase 确实是 closing（非 stale callback）
    if (blinkPhaseRef.current === "closing") {
      onCloseComplete?.();
    }
  }, [onCloseComplete]);

  const handleOpenComplete = useCallback(() => {
    if (completedRef.current.open) return;
    completedRef.current.open = true;
    if (blinkPhaseRef.current === "opening") {
      onOpenComplete?.();
    }
  }, [onOpenComplete]);

  // 当 blinkPhase 为 null 时不渲染
  const isVisible = blinkPhase !== null;
  const isClosed = blinkPhase === "closing" || blinkPhase === "paused";

  return (
    <AnimatePresence>
      {isVisible && (
        <>
          {/* ── 上眼皮 ── */}
          <motion.div
            className="fixed inset-x-0 top-0 z-[1500] overflow-hidden"
            style={{ height: "51vh" }} // 51vh 确保与下眼皮有 1vh 重叠，不留缝隙
            initial={{ y: "-100%" }}
            animate={{ y: isClosed ? "0%" : "-100%" }}
            exit={{ y: "-100%" }}
            transition={{
              duration: blinkPhase === "closing" ? CLOSE_DURATION : OPEN_DURATION,
              ease: eyelidEase,
            }}
            onAnimationComplete={
              blinkPhase === "closing" ? handleCloseComplete
              : blinkPhase === "opening" ? handleOpenComplete
              : undefined
            }
          >
            {/* 主遮罩：深蓝黑渐变 */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "linear-gradient(to bottom, #08081e 0%, #050514 50%, #02020e 100%)",
              }}
            />
            {/* 眼皮下缘柔化：模拟睫毛/眼睑边缘的模糊过渡 */}
            <div
              className="absolute bottom-0 inset-x-0 h-20"
              style={{
                background:
                  "linear-gradient(to bottom, transparent 0%, rgba(3,3,18,0.4) 40%, rgba(2,2,14,0.7) 100%)",
              }}
            />
            <div
              className="absolute bottom-0 inset-x-0 h-8"
              style={{
                backdropFilter: "blur(6px)",
                WebkitBackdropFilter: "blur(6px)",
                maskImage:
                  "linear-gradient(to bottom, transparent 0%, black 100%)",
                WebkitMaskImage:
                  "linear-gradient(to bottom, transparent 0%, black 100%)",
              }}
            />
            {/* 暗角效果 */}
            <div
              className="absolute inset-0"
              style={{
                boxShadow: "inset 0 0 120px 50px rgba(0,0,0,0.35)",
              }}
            />
            {/* 中心区域更暗 — 模拟眼皮弧度 */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse 80% 30% at center bottom, rgba(0,0,0,0.5) 0%, transparent 100%)",
              }}
            />
          </motion.div>

          {/* ── 下眼皮 ── */}
          <motion.div
            className="fixed inset-x-0 bottom-0 z-[1500] overflow-hidden"
            style={{ height: "51vh" }}
            initial={{ y: "100%" }}
            animate={{ y: isClosed ? "0%" : "100%" }}
            exit={{ y: "100%" }}
            transition={{
              duration: blinkPhase === "closing" ? CLOSE_DURATION : OPEN_DURATION,
              ease: eyelidEase,
            }}
            onAnimationComplete={
              blinkPhase === "closing" ? handleCloseComplete
              : blinkPhase === "opening" ? handleOpenComplete
              : undefined
            }
          >
            {/* 主遮罩：深蓝黑渐变（下眼皮方向相反） */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "linear-gradient(to top, #08081e 0%, #050514 50%, #02020e 100%)",
              }}
            />
            {/* 眼皮上缘柔化 */}
            <div
              className="absolute top-0 inset-x-0 h-20"
              style={{
                background:
                  "linear-gradient(to top, transparent 0%, rgba(3,3,18,0.4) 40%, rgba(2,2,14,0.7) 100%)",
              }}
            />
            <div
              className="absolute top-0 inset-x-0 h-8"
              style={{
                backdropFilter: "blur(6px)",
                WebkitBackdropFilter: "blur(6px)",
                maskImage:
                  "linear-gradient(to top, transparent 0%, black 100%)",
                WebkitMaskImage:
                  "linear-gradient(to top, transparent 0%, black 100%)",
              }}
            />
            {/* 暗角 */}
            <div
              className="absolute inset-0"
              style={{
                boxShadow: "inset 0 0 120px 50px rgba(0,0,0,0.35)",
              }}
            />
            {/* 中心弧度 */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(ellipse 80% 30% at center top, rgba(0,0,0,0.5) 0%, transparent 100%)",
              }}
            />
          </motion.div>

          {/* ── 缝隙填充层：在上下眼皮即将闭合时，覆盖可能的极细缝隙 ── */}
          <motion.div
            className="fixed inset-0 z-[1499] pointer-events-none"
            initial={{ opacity: 0 }}
            animate={{ opacity: isClosed ? 1 : 0 }}
            exit={{ opacity: 0 }}
            transition={{
              duration: 0.15,
              delay: isClosed ? CLOSE_DURATION * 0.85 : 0,
            }}
            style={{
              background: "#02020e",
            }}
          />
        </>
      )}
    </AnimatePresence>
  );
}
