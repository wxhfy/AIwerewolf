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
}

export function PlayerRail({
  players,
  fallbackPlayers,
  pendingPlayerId,
  activeSpeakerId,
  sheriffId,
  badgeCandidateSet,
  isHumanMode,
  humanSeat,
  wolfTeammates,
  side,
}: PlayerRailProps) {
  const visiblePlayers = players.length > 0 ? players : fallbackPlayers;
  return (
    <aside className={`hidden w-[21%] min-w-[150px] flex-col gap-2 overflow-y-auto p-3 lg:flex [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none] ${side === "left" ? "border-r" : "border-l"} border-border`}>
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
        />
      ))}
    </aside>
  );
}

interface MobilePlayerRailProps extends Omit<PlayerRailProps, "side"> {}

export function MobilePlayerRail({
  players,
  fallbackPlayers,
  pendingPlayerId,
  activeSpeakerId,
  sheriffId,
  badgeCandidateSet,
  isHumanMode,
  humanSeat,
  wolfTeammates,
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
          />
        </div>
      ))}
    </div>
  );
}
