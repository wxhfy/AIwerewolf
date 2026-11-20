/**
 * Stable avatar mapping for AI Werewolf seats.
 * Maps seat numbers 1..7 directly to character portraits.
 * Seats > 7 cycle cleanly with ((seat - 1) % 7) + 1.
 * Never keyed off role, name, or persona so hidden information never leaks.
 */
export function seatAvatarSrc(seat: number | string): string {
  const n = ((Math.max(1, Math.floor(Number(seat) || 1)) - 1) % 7) + 1;
  return `/avatars/seat-${n}.webp`;
}
