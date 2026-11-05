"use client";

import { Player } from "@/types";
import { PlayerCard } from "@/components/game/PlayerCard";

interface PlayerRailProps {
  players: Player[];
  fallbackPlayers: Player[];
  pendingPlayerId?: string;
  activeSpeakerId?: string | null;
  sheriffId?: string | null;
  badgeCandidateSet: Set<string>;
  isHumanMode: boolean;
  humanSeat: number;
  wolfTeammates?: string[];
  side: "left" | "right";
  spokenInPhase: Set<string>;
  /** 夜间角色信息，用于高亮匹配角色的玩家卡片 */
  nightRoleInfo?: { roles: string[]; pendingActorId: string | null; roleMatchedIds: string[] } | null;
  /** 当前游戏阶段，用于区分发言中/行动中标签 */
  currentPhase?: string;
  /** Target selection mode — when true, cards are clickable to select */
  selectable?: boolean;
  selectableIds?: Set<string>;
  selectedTargetId?: string;
  onSelectTarget?: (id: string) => void;
  /** 统一发言状态 */
  speakerState?: { state: 'thinking' | 'speaking' | 'finished'; speakerId: string | null };
}

export function PlayerRail({
  players, fallbackPlayers, pendingPlayerId, activeSpeakerId,
  sheriffId, badgeCandidateSet, isHumanMode, humanSeat,
  wolfTeammates, side, spokenInPhase, nightRoleInfo, currentPhase,
  selectable, selectableIds, selectedTargetId, onSelectTarget, speakerState,
}: PlayerRailProps) {
  const visiblePlayers = players.length > 0 ? players : fallbackPlayers;
  // 公开视角下用 pendingActorId 匹配（不泄露角色），主持视角下用角色匹配
  const nightActiveSet = new Set<string>();
  if (nightRoleInfo) {
    if (isHumanMode) {
      // 公开/真人视角：只高亮当前行动者，不泄露角色
      if (nightRoleInfo.pendingActorId) nightActiveSet.add(nightRoleInfo.pendingActorId);
    } else {
      // 主持视角：高亮所有匹配角色的存活玩家
      for (const id of nightRoleInfo.roleMatchedIds) nightActiveSet.add(id);
    }
  }
  return (
    <aside aria-label={side === "left" ? "玩家席位 1" : "玩家席位 2"} className={`hidden w-[23%] min-w-[220px] max-w-[320px] shrink-0 flex-col gap-3 overflow-y-auto overscroll-contain bg-cardBackground/20 p-3 lg:flex timeline-scroll ${side === "left" ? "border-r" : "border-l"} border-border`}>
      {visiblePlayers.map((player, index) => (
        <PlayerCard
          key={player.id || index}
          player={player}
          isSpeaking={
              // 仅发言阶段用统一speakerState判断，其他阶段走原逻辑
              (speakerState && speakerState.speakerId != null)
                ? speakerState.state === 'speaking' && speakerState.speakerId === player.id
                : pendingPlayerId === player.id
            }
            isThinking={
              // 仅发言阶段用统一speakerState判断，其他阶段走原逻辑
              (speakerState && speakerState.speakerId != null)
                ? speakerState.state === 'thinking' && speakerState.speakerId === player.id
                : !pendingPlayerId && activeSpeakerId === player.id
            }
          isNightActive={nightActiveSet.has(player.id) && player.alive && pendingPlayerId !== player.id}
          currentPhase={currentPhase}
          isSheriff={sheriffId === player.id}
          isBadgeCandidate={badgeCandidateSet.has(player.id)}
          showOwnRole={isHumanMode && player.seat === humanSeat}
          wolfTeammates={isHumanMode && player.seat === humanSeat ? wolfTeammates : undefined}
          hasSpoken={spokenInPhase.has(player.id)}
          selectable={
            selectable &&
            player.alive &&
            player.id !== (pendingPlayerId || activeSpeakerId || "") &&
            (!selectableIds || selectableIds.has(player.id))
          }
          isTarget={selectedTargetId === player.id}
          onSelectTarget={onSelectTarget ? () => onSelectTarget(player.id) : undefined}
        />
      ))}
    </aside>
  );
}

interface MobilePlayerRailProps extends Omit<PlayerRailProps, "side"> {}

export function MobilePlayerRail({
  players, fallbackPlayers, pendingPlayerId, activeSpeakerId,
  sheriffId, badgeCandidateSet, isHumanMode, humanSeat,
  wolfTeammates, spokenInPhase, nightRoleInfo, currentPhase,
  selectable, selectableIds, selectedTargetId, onSelectTarget, speakerState,
}: MobilePlayerRailProps) {
  const visiblePlayers = players.length > 0 ? players : fallbackPlayers;
  // 公开视角下用 pendingActorId 匹配（不泄露角色），主持视角下用角色匹配
  const nightActiveSet = new Set<string>();
  if (nightRoleInfo) {
    if (isHumanMode) {
      // 公开/真人视角：只高亮当前行动者，不泄露角色
      if (nightRoleInfo.pendingActorId) nightActiveSet.add(nightRoleInfo.pendingActorId);
    } else {
      // 主持视角：高亮所有匹配角色的存活玩家
      for (const id of nightRoleInfo.roleMatchedIds) nightActiveSet.add(id);
    }
  }
  return (
    <div role="region" aria-label="玩家席位 · 横向滚动查看" tabIndex={0} className="relative z-10 flex shrink-0 snap-x snap-proximity gap-2 overflow-x-auto overscroll-x-contain border-b border-border bg-cardBackground/30 px-3 py-2 lg:hidden timeline-scroll [@media(max-height:500px)]:py-1">
      {visiblePlayers.map((player, index) => (
        <div key={player.id || index} className="w-[164px] shrink-0 snap-start">
          <PlayerCard
            compact
            player={player}
            isSpeaking={
              // 仅发言阶段用统一speakerState判断，其他阶段走原逻辑
              (speakerState && speakerState.speakerId != null)
                ? speakerState.state === 'speaking' && speakerState.speakerId === player.id
                : pendingPlayerId === player.id
            }
            isThinking={
              // 仅发言阶段用统一speakerState判断，其他阶段走原逻辑
              (speakerState && speakerState.speakerId != null)
                ? speakerState.state === 'thinking' && speakerState.speakerId === player.id
                : !pendingPlayerId && activeSpeakerId === player.id
            }
            isNightActive={nightActiveSet.has(player.id) && player.alive && pendingPlayerId !== player.id}
            currentPhase={currentPhase}
            isSheriff={sheriffId === player.id}
            isBadgeCandidate={badgeCandidateSet.has(player.id)}
            showOwnRole={isHumanMode && player.seat === humanSeat}
            wolfTeammates={isHumanMode && player.seat === humanSeat ? wolfTeammates : undefined}
            hasSpoken={spokenInPhase.has(player.id)}
            selectable={
              selectable &&
              player.alive &&
              player.id !== (pendingPlayerId || activeSpeakerId || "") &&
              (!selectableIds || selectableIds.has(player.id))
            }
            isTarget={selectedTargetId === player.id}
            onSelectTarget={onSelectTarget ? () => onSelectTarget(player.id) : undefined}
          />
        </div>
      ))}
    </div>
  );
}
