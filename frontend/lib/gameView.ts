import { Language, Player } from "@/types";

export function placeholderPlayers(from: number, to: number, language: Language, humanSeat: number): Player[] {
  const players: Player[] = [];
  for (let seat = from; seat <= to; seat += 1) {
    players.push({
      id: `ph-${seat}`,
      seat,
      name: language === Language.ZH ? `玩家 ${seat}` : `Player ${seat}`,
      alive: true,
      is_ai: seat !== humanSeat,
    });
  }
  return players;
}
