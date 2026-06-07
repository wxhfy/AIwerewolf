"use client";

import React, { useEffect, useRef } from "react";
import { EventType, GameEvent, Language, ViewMode, Player, NightActions } from "@/types";
import { t, format } from "@/lib/i18n";
import { TimelineEvent } from "./TimelineEvent";
import { ChatBubble } from "@/components/game/ChatBubble";
import { VoteResultPanel } from "@/components/game/VoteResultPanel";

// ── Types ────────────────────────────────────────────────────────────

type DecisionRecordLike = Record<string, unknown> & {
  player_id?: string;
  day?: number;
  request?: string;
  parsed_action?: Record<string, unknown> & {
    action_type?: string;
    target_id?: string | null;
    speech?: string;
    reasoning?: string;
  };
};

export interface DayEventBlockProps {
  day: number;
  events: GameEvent[];
  language: Language;
  viewMode: ViewMode;
  isHumanMode: boolean;
  humanSeat: number;
  completedIds: Set<string>;
  onChatComplete: (eventId: string) => void;
  hideDayHeaders?: boolean;
  dayVotes?: Record<string, string>;
  players?: Player[];
  nightActions?: NightActions | null;
  decisionRecords?: DecisionRecordLike[] | null | undefined;
  isTransitioning?: boolean;
  currentDay?: number;
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
}

// ── Helpers ──────────────────────────────────────────────────────────

function isRedundantPhaseAnnouncement(event: GameEvent): boolean {
  if (event.type === EventType.SYSTEM_MESSAGE) {
    const msg = event.payload.message || "";
    return /^Night \d+ begins\.$/.test(msg)
        || /^Day \d+ begins\.$/.test(msg)
        || /was voted out\.$/.test(msg);  // elimination confirmed after last words
  }
  if (event.type === EventType.PHASE_CHANGED && event.payload.phase === "GAME_END") {
    return true;
  }
  return false;
}

function mergeConsecutiveChats(events: GameEvent[]): GameEvent[] {
  const merged: GameEvent[] = [];
  for (const event of events) {
    const prev = merged[merged.length - 1];
    // Don't merge multi-segment speeches (segment_total > 1) — they are
    // intentionally separate bubbles from the backend
    const isMultiSegment = (event.payload as any)?.segment_total > 1
      || (prev?.payload as any)?.segment_total > 1;
    if (
      !isMultiSegment &&
      prev && event.type === EventType.CHAT_MESSAGE && prev.type === EventType.CHAT_MESSAGE &&
      event.payload.actor_id && event.payload.actor_id === prev.payload.actor_id &&
      event.phase === prev.phase &&
      !(event.payload as any).last_words && !(prev.payload as any).last_words
    ) {
      const prevSpeech = (prev.payload.speech as string) || "";
      const curSpeech = (event.payload.speech as string) || "";
      merged[merged.length - 1] = {
        ...prev,
        payload: { ...prev.payload, speech: prevSpeech ? `${prevSpeech}\n\n${curSpeech}` : curSpeech },
      };
    } else {
      merged.push(event);
    }
  }
  return merged;
}

function buildWolfDeliberation(
  day: number, nightActions: NightActions | null | undefined,
  decisionRecords: DecisionRecordLike[] | null | undefined,
  players: Player[], language: Language,
): Array<{ kind: "discuss" | "vote" | "result"; text: string }> {
  const entries: Array<{ kind: "discuss" | "vote" | "result"; text: string }> = [];
  const wolfVotes = nightActions?.wolf_votes;
  const wolfTargetId = nightActions?.wolf_target_id;

  // Build a set of wolf player IDs for filtering
  const wolfPlayerIds = new Set(
    (players || []).filter(p => p.alignment === "wolf" && p.alive).map(p => p.id)
  );

  // ── Discuss header ──────────────────────────────────────────────────
  entries.push({ kind: "discuss", text: t("wolfDiscussing", language) });

  // ── Individual votes: only show if they match or can be corrected to the final target ──
  const rawVotes: Array<{ wolfId: string; targetId: string }> = [];

  if (wolfVotes && Object.keys(wolfVotes).length > 0) {
    for (const [wolfId, targetId] of Object.entries(wolfVotes)) {
      rawVotes.push({ wolfId, targetId });
    }
  } else {
    // Fallback: use decision_records
    const wolfDecisions = (decisionRecords || []).filter(
      d => d.request === "WOLF_TEAM_VOTE" && d.day === day
    );
    for (const d of wolfDecisions) {
      rawVotes.push({
        wolfId: d.player_id || "",
        targetId: d.parsed_action?.target_id || "",
      });
    }
  }

  if (rawVotes.length === 0) return entries;

  // 检查是否所有存活狼人都已投票
  const allWolvesVoted = [...wolfPlayerIds].every(wolfId =>
    rawVotes.some(v => v.wolfId === wolfId)
  );

  // Resolved target: backend's wolf_target_id takes priority,
  // otherwise all-same-vote → first vote's target
  const allSameTarget = new Set(rawVotes.map(v => v.targetId)).size <= 1;
  const resolvedId = wolfTargetId || (allSameTarget ? rawVotes[0].targetId : null);
  const resolvedPlayer = resolvedId ? players.find(p => p.id === resolvedId) : undefined;

  // ── Show individual votes, corrected to resolved target if it exists ──
  for (const { wolfId } of rawVotes) {
    const wolf = players.find(p => p.id === wolfId);
    if (!wolf?.alive) continue;
    // Use resolved target if available; otherwise use the raw vote
    const displayTargetId = resolvedId || rawVotes.find(v => v.wolfId === wolfId)?.targetId || "";
    const displayTarget = players.find(p => p.id === displayTargetId);
    // Skip if the target is a wolf (should never happen with correct data)
    if (displayTargetId && wolfPlayerIds.has(displayTargetId)) continue;
    entries.push({
      kind: "vote",
      text: format(t("wolfVoted", language), {
        name: wolf.name || wolfId,
        target: String(displayTarget?.seat || displayTargetId || "?"),
      }),
    });
  }

  // ── Final decision（仅当所有狼人投票完成后） ──────────────────────
  if (allWolvesVoted) {
    if (resolvedPlayer) {
      entries.push({
        kind: "result",
        text: format(t("wolfFinalTarget"), {
          target: String(resolvedPlayer.seat),
          name: resolvedPlayer.name || "",
        }),
      });
    } else if (!allSameTarget) {
      entries.push({ kind: "result", text: t("wolfNoConsensus") });
    }
  }
  return entries;
}

// ── VoteResultInline ──────────────────────────────────────────────────

function VoteResultInline({ votes, players, language }: {
  votes: Record<string, string>; players: Player[]; language: Language;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, []);
  return (
    <div ref={ref}>
      <VoteResultPanel votes={votes} players={players} language={language} isBadgeVote={false} />
    </div>
  );
}

// ── DayEventBlock ────────────────────────────────────────────────────

export function DayEventBlock({
  day, events, language, viewMode, isHumanMode, humanSeat,
  completedIds, onChatComplete, hideDayHeaders, dayVotes, players,
  nightActions, decisionRecords, isTransitioning, currentDay, speakerState,
}: DayEventBlockProps) {
  const rawEvents = events.filter(event =>
    event.type !== EventType.PRIVATE_INFO &&
    (viewMode === ViewMode.MODERATOR || event.visibility !== "private") &&
    !isRedundantPhaseAnnouncement(event) &&
    // 过滤狼人行动阶段的单独行动事件，统一显示聚合后的狼队商议内容
    !(event.phase === "NIGHT_WOLF_ACTION" && event.type === EventType.NIGHT_ACTION) &&
    // 过滤投票放逐的 PLAYER_DIED 事件，统一在遗言后渲染一次确认
    !(event.type === EventType.PLAYER_DIED && (event.payload as any)?.reason === "vote")
  );

  const timelineEvents = mergeConsecutiveChats(rawEvents);
  const deaths = rawEvents.filter(e =>
    e.type === EventType.PLAYER_DIED || e.type === EventType.HUNTER_SHOT || e.type === EventType.WHITE_WOLF_KING_BOOM
  );

  if (timelineEvents.length === 0) return null;

  // Archive cutoff: the bottom dialogue dock owns the active speech.
  // Timeline only shows CHAT_MESSAGE events after the dock has completed them.
  let archiveCutoff = timelineEvents.length;
  for (let i = 0; i < timelineEvents.length; i++) {
    if (timelineEvents[i].type === EventType.CHAT_MESSAGE && !completedIds.has(timelineEvents[i].id)) {
      archiveCutoff = i; break;
    }
  }
  const visibleEvents = timelineEvents.slice(0, archiveCutoff);
  // System events after archiveCutoff (deaths, hunter shoot, etc.) should render immediately
  const pendingSystemEvents = timelineEvents.slice(archiveCutoff).filter(e =>
    e.type !== EventType.CHAT_MESSAGE && e.type !== EventType.VOTE_CAST
  );

  // Vote result cutoff: show before LAST_WORDS / HUNTER_SHOOT / BADGE_TRANSFER
  let voteCutoff = timelineEvents.length;
  for (let i = 0; i < timelineEvents.length; i++) {
    const ph = timelineEvents[i].phase || "";
    if (ph === "DAY_LAST_WORDS" || ph === "HUNTER_SHOOT" || ph === "BADGE_TRANSFER") { voteCutoff = i; break; }
  }
  const voteResultReady = archiveCutoff >= voteCutoff;

  return (
    <div className="mb-5">
      {!hideDayHeaders && (
        <div className="mb-3 flex items-center gap-3 border-b border-border pb-2">
          <span className="font-display text-lg font-bold text-primary tracking-wide">
            {day === 0
              ? `🎭 ${t("dayHeaderSetup", language)}`
              : `🌅 ${t("dayHeaderLabel", language).replace("{n}", String(day))}`}
          </span>
          {deaths.length > 0 && (
            <span className="truncate text-xs text-danger">
              {deaths.map(d => d.payload.player_name || d.payload.target_name || "?").join(" · ")} {t("playerDied", language)}
            </span>
          )}
        </div>
      )}

      {/* Events — wolf deliberation inserted inline after NIGHT_WOLF_ACTION phase change */}
      <div className="space-y-0.5">
        {(() => {
          // Find insert position: right after "狼人请睁眼" PHASE_CHANGED event
          let wolfInsertAt = -1;
          for (let i = 0; i < visibleEvents.length; i++) {
            if (visibleEvents[i].phase === "NIGHT_WOLF_ACTION" && visibleEvents[i].type === EventType.PHASE_CHANGED) {
              wolfInsertAt = i + 1;
              break;
            }
          }
          const showWolf = viewMode === ViewMode.MODERATOR && day > 0 && (day <= (currentDay ?? day)) && !isTransitioning && wolfInsertAt > 0;
          const wolfEntries = showWolf
            ? buildWolfDeliberation(day, nightActions, decisionRecords, players || [], language)
            : [];

          const nodes: React.ReactNode[] = [];
          const preCutoff = Math.min(voteCutoff, visibleEvents.length);

          for (let i = 0; i < preCutoff; i++) {
            const evt = visibleEvents[i];
            nodes.push(
              <TimelineEvent
                key={evt.id || i} event={evt} index={i}
                language={language} isHumanMode={isHumanMode} humanSeat={humanSeat}
                players={players}
                animateChat={false}
                onChatComplete={onChatComplete} isLatest={false}
              />
            );
            // Insert wolf deliberation right after "狼人请睁眼" phase change
            if (i === wolfInsertAt - 1 && wolfEntries.length > 0) {
              nodes.push(
                <div key={`wolf-p-${day}`} className="ml-2 border-l-2 border-primary/15 pl-3 py-1 space-y-1 mb-1">
                  {wolfEntries.map((entry, j) => (
                    <div key={`wolf-${day}-${j}`} className="flex items-center gap-2">
                      <span className="text-xs text-primary/50 shrink-0">
                        {entry.kind === "discuss" ? "🐺" : entry.kind === "vote" ? "▸" : "✓"}
                      </span>
                      <span className={entry.kind === "result" ? "text-sm font-medium text-primary" : "text-sm text-text-sub/80"}>
                        {entry.text}
                      </span>
                    </div>
                  ))}
                </div>
              );
            }
          }

          // 插入发言思考阶段占位卡片
          if (
            speakerState?.state === "thinking" && 
            speakerState.speakerId && 
            players &&
            // 仅当前天的发言阶段显示
            day === currentDay &&
            visibleEvents.some(e => e.phase?.includes("SPEECH"))
          ) {
            const thinkingPlayer = players.find(p => p.id === speakerState.speakerId);
            if (thinkingPlayer) {
              nodes.push(
                <ChatBubble
                  key="thinking-placeholder"
                  speakerName={thinkingPlayer.name || "?"}
                  seat={thinkingPlayer.seat}
                  content={language === "zh" ? "正在组织语言..." : "Thinking..."}
                  isOwn={isHumanMode && thinkingPlayer.seat === humanSeat}
                  isSpeaking={false}
                  animate={false}
                  players={players}
                />
              );
            }
          }

          // 渲染被 revealIndex 挡住的系统事件（死亡、猎人开枪等不阻塞）
          for (const evt of pendingSystemEvents) {
            nodes.push(
              <TimelineEvent
                key={evt.id || `sys-${nodes.length}`} event={evt} index={nodes.length}
                language={language} isHumanMode={isHumanMode} humanSeat={humanSeat}
                players={players} animateChat={false}
                onChatComplete={onChatComplete} isLatest={false}
              />
            );
          }

          return nodes;
        })()}

        {/* Vote result inline */}
        {dayVotes && Object.keys(dayVotes).length > 0 && voteResultReady && (
          <VoteResultInline votes={dayVotes} players={players || []} language={language} />
        )}

        {visibleEvents.slice(voteCutoff).map((event, index) => (
          <TimelineEvent
            key={event.id || index} event={event} index={index + voteCutoff}
            language={language} isHumanMode={isHumanMode} humanSeat={humanSeat}
            players={players}
            animateChat={false}
            onChatComplete={onChatComplete}
            isLatest={false}
          />
        ))}

        {/* ── Elimination confirmation: once after last words ── */}
        {(() => {
          // Only for exile votes (not badge), and only after last words rendered
          if (!dayVotes || Object.keys(dayVotes).length === 0) return null;
          const hasLastWords = timelineEvents.some(e => e.phase === "DAY_LAST_WORDS");
          if (!hasLastWords) return null;
          const lastWordsIdx = timelineEvents.findIndex(e => e.phase === "DAY_LAST_WORDS");
          if (archiveCutoff <= lastWordsIdx) return null; // not yet archived
          // Find top vote getter
          const tally: Record<string, number> = {};
          for (const targetId of Object.values(dayVotes)) {
            tally[targetId] = (tally[targetId] || 0) + 1;
          }
          const topId = Object.entries(tally).sort((a, b) => b[1] - a[1])[0]?.[0];
          if (!topId) return null;
          const exiled = players?.find(p => p.id === topId);
          if (!exiled || exiled.alive) return null;
          const text = language === "zh"
            ? `${exiled.seat}号 ${exiled.name} 因投票放逐出局`
            : `#${exiled.seat} ${exiled.name} was exiled by vote`;
          return (
            <div className="flex justify-center py-2">
              <span className="text-xs text-danger/60 font-medium tracking-wide">
                ◆ {text}
              </span>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
