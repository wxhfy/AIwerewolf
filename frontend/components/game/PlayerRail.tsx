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
  votedSet: Set<string>;
  voteCount: Map<string, number>;
  /** Maps voterId → target player name */
  voteTarget: Map<string, string>;
  /** Target selection mode — when true, cards are clickable to select */
  selectable?: boolean;
  selectedTargetId?: string;
  onSelectTarget?: (id: string) => void;
}

export function PlayerRail({
  players, fallbackPlayers, pendingPlayerId, activeSpeakerId,
  sheriffId, badgeCandidateSet, isHumanMode, humanSeat,
  wolfTeammates, side, spokenInPhase, votedSet, voteCount, voteTarget,
  selectable, selectedTargetId, onSelectTarget,
}: PlayerRailProps) {
  const visiblePlayers = players.length > 0 ? players : fallbackPlayers;
  return (
    <aside className={`hidden w-[21%] min-w-[150px] flex-col gap-2 overflow-y-auto p-3 lg:flex timeline-scroll ${side === "left" ? "border-r" : "border-l"} border-border`}>
      {visiblePlayers.map((player, index) => (
        <PlayerCard
          key={player.id || index}
          player={player}
          isSpeaking={pendingPlayerId === player.id}
          isThinking={!pendingPlayerId && activeSpeakerId === player.id}
          isSheriff={sheriffId === player.id}
          isBadgeCandidate={badgeCandidateSet.has(player.id)}
          showOwnRole={isHumanMode && player.seat === humanSeat}
          wolfTeammates={isHumanMode && player.seat === humanSeat ? wolfTeammates : undefined}
          hasSpoken={spokenInPhase.has(player.id)}
          hasVoted={votedSet.has(player.id)}
          voteCount={voteCount.get(player.id) || 0}
          voteTargetName={voteTarget.get(player.id)}
          selectable={selectable && player.alive && player.id !== (pendingPlayerId || activeSpeakerId || "")}
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
  wolfTeammates, spokenInPhase, votedSet, voteCount, voteTarget,
  selectable, selectedTargetId, onSelectTarget,
}: MobilePlayerRailProps) {
  const visiblePlayers = players.length > 0 ? players : fallbackPlayers;
  return (
    <div className="relative z-10 flex gap-2 overflow-x-auto px-4 py-2 lg:hidden">
      {visiblePlayers.map((player, index) => (
        <div key={player.id || index} className="w-[100px] flex-shrink-0">
          <PlayerCard
            player={player}
            isSpeaking={pendingPlayerId === player.id}
            isThinking={!pendingPlayerId && activeSpeakerId === player.id}
            isSheriff={sheriffId === player.id}
            isBadgeCandidate={badgeCandidateSet.has(player.id)}
            showOwnRole={isHumanMode && player.seat === humanSeat}
            wolfTeammates={isHumanMode && player.seat === humanSeat ? wolfTeammates : undefined}
            hasSpoken={spokenInPhase.has(player.id)}
            hasVoted={votedSet.has(player.id)}
            voteCount={voteCount.get(player.id) || 0}
            voteTargetName={voteTarget.get(player.id)}
            selectable={selectable && player.alive && player.id !== (pendingPlayerId || activeSpeakerId || "")}
            isSelected={selectedTargetId === player.id}
            onSelectTarget={onSelectTarget ? () => onSelectTarget(player.id) : undefined}
          />
        </div>
      ))}
    </div>
  );
}
