/**
 * deriveStatusText — 纯函数，根据 gameState 计算状态栏文本。
 * 从 page.tsx 提取，可独立测试。
 */
import { GameState, Language, Phase } from "@/types";
import { t, tPhase, tPhaseStatus, format } from "@/lib/i18n";

export interface StatusText {
  statusTitle: string;
  actionText: string;
}

export function deriveStatusText(
  gameState: GameState | null,
  language: Language,
): StatusText {
  const pending = gameState?.pending_input;
  const phase = gameState?.phase || "";
  const players = gameState?.players || [];

  // ── 1. 有 pending_input 且阶段匹配：显示具体玩家动作 ──
  // ⚠️  必须校验 pending.phase === gameState.phase，防止上一阶段残留的
  // pending_input 导致状态栏显示错误的玩家（如2号发言但显示1号发言中）
  if (pending && pending.phase === phase) {
    const seat = pending.seat;
    const name = pending.player_name;
    const actionType = pending.action_type;

    let actionKey: string;
    if (actionType === "speech" || actionType === "badge_speech") {
      actionKey = "playerSpeakingStatus";
    } else if (actionType === "vote" || actionType === "badge_vote") {
      actionKey = "playerVotingStatus";
    } else {
      actionKey = "playerActingStatus";
    }

    const actionText = format(t(actionKey as any, language), { seat: String(seat), name });

    const hasSpeakingEvent = (gameState?.events || []).some(
      e => e.type === "CHAT_MESSAGE" && e.phase === phase && (e.payload as any)?.actor_id === pending.player_id
    );
    const thinkingText = format(t("playerThinkingStatus" as any, language), { seat: String(seat), name });

    if (actionType === "speech" || actionType === "badge_speech") {
      if (hasSpeakingEvent) {
        return { statusTitle: t("statusStreaming", language), actionText };
      }
      return { statusTitle: t("statusStreaming", language), actionText: thinkingText };
    }

    return { statusTitle: t("statusStreaming", language), actionText };
  }

  // ── 2. 夜间阶段 ──
  if (phase.startsWith("NIGHT_")) {
    const statusLabel = tPhaseStatus(phase, language);
    return { statusTitle: statusLabel || t("statusStreaming", language), actionText: "" };
  }

  // ── 3. 白天发言/投票阶段 ──
  if (phase.startsWith("DAY_")) {
    const isVotePhase = phase.includes("VOTE") || phase.includes("ELECTION");
    const isPkSpeech = phase === "DAY_PK_SPEECH";

    if (isVotePhase && !isPkSpeech) {
      const voters = new Set<string>();
      for (const e of (gameState?.events || [])) {
        if (e.type === "VOTE_CAST") {
          const vid = (e.payload as any)?.voter_id;
          if (vid) voters.add(vid);
        }
      }
      // 警徽投票时，候选人只被投、不投票，需排除
      const badge = gameState?.badge;
      const isBadgeElection = phase.includes("BADGE");
      const candidateIds = isBadgeElection
        ? new Set(badge?.candidates?.length ? badge.candidates : Object.values(badge?.votes || {}))
        : new Set<string>();
      const unvoted = (gameState?.players || []).filter(
        p => p.alive && !voters.has(p.id) && !candidateIds.has(p.id)
      );
      if (unvoted.length > 0) {
        const nextVoter = unvoted[0];
        const waitText = language === Language.ZH
          ? `等待 ${nextVoter.seat}号 ${nextVoter.name} 投票`
          : `Waiting for #${nextVoter.seat} ${nextVoter.name} to vote`;
        return { statusTitle: waitText, actionText: "" };
      }
      const statusLabel = tPhaseStatus(phase, language);
      return { statusTitle: statusLabel || (language === Language.ZH ? "投票中" : "Voting"), actionText: "" };
    }

    if (isPkSpeech) {
      const speakerId = gameState?.current_speaker_id;
      if (speakerId) {
        const speaker = players.find(p => p.id === speakerId && p.alive);
        if (speaker) {
          const text = format(t("playerSpeakingStatus" as any, language), { seat: String(speaker.seat), name: speaker.name });
          return { statusTitle: text, actionText: "" };
        }
      }
      return { statusTitle: language === Language.ZH ? "PK 发言中" : "PK Speech", actionText: "" };
    }

    const speakerId = gameState?.current_speaker_id;
    if (speakerId) {
      const speaker = players.find(p => p.id === speakerId && p.alive);
      if (speaker) {
        const speakingText = format(t("playerSpeakingStatus" as any, language), { seat: String(speaker.seat), name: speaker.name });
        return { statusTitle: speakingText, actionText: "" };
      }
    }
    const statusLabel = tPhaseStatus(phase, language);
    if (statusLabel) {
      return { statusTitle: statusLabel, actionText: "" };
    }
    return { statusTitle: tPhase(phase, language), actionText: "" };
  }

  // ── 4. 特殊阶段 ──
  if (phase === Phase.HUNTER_SHOOT) {
    return { statusTitle: tPhaseStatus("HUNTER_SHOOT", language), actionText: "" };
  }
  if (phase === Phase.GAME_END || gameState?.winner) {
    return { statusTitle: t("statusLoaded", language), actionText: "" };
  }

  return { statusTitle: t("statusStreaming", language), actionText: "" };
}
