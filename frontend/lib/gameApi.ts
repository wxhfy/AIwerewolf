import { AgentType, GameState, RoomRecord } from "@/types";
import { apiUrl } from "@/lib/api";

export type GameMode = "ai" | "human";

const requestTimeoutMs = 30000;

interface CreateRoomParams {
  seed: number;
  playerCount: number;
  agentType: AgentType;
  mode: GameMode;
  humanSeat: number;
}

interface HumanActionPayload {
  target_id?: string | null;
  speech?: string | null;
  save?: boolean;
}

async function parseJson<T>(response: Response): Promise<T> {
  return response.json() as Promise<T>;
}

async function fetchWithTimeout(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("requestTimeout");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function createRoom({ seed, playerCount, agentType, mode, humanSeat }: CreateRoomParams): Promise<RoomRecord> {
  const params = new URLSearchParams({
    name: "Demo Room",
    seed: String(seed),
    player_count: String(playerCount),
    agent_type: agentType,
  });
  if (mode === "human") params.set("human_seat", String(humanSeat));

  const response = await fetchWithTimeout(apiUrl(`/api/rooms?${params.toString()}`), { method: "POST" });
  if (!response.ok) throw new Error(`Failed to create room (${response.status})`);
  return parseJson<RoomRecord>(response);
}

export async function prepareRoom(roomId: string, showPrivate = false): Promise<GameState> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/prepare?show_private=${showPrivate ? "true" : "false"}`), { method: "POST" });
  if (!response.ok) throw new Error(`Prepare failed (${response.status})`);
  return parseJson<GameState>(response);
}

export async function startRoom(roomId: string, showPrivate = false): Promise<GameState> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/start?show_private=${showPrivate ? "true" : "false"}`), { method: "POST" });
  if (!response.ok) throw new Error(`Start failed (${response.status})`);
  return parseJson<GameState>(response);
}

export async function fetchRoom(roomId: string): Promise<RoomRecord | null> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}`));
  if (!response.ok) return null;
  return parseJson<RoomRecord>(response);
}

export async function submitHumanAction(roomId: string, data: HumanActionPayload): Promise<GameState> {
  const url = apiUrl(`/api/rooms/${roomId}/action`);
  const response = await fetchWithTimeout(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_id: data.target_id || null,
      speech: data.speech || null,
      save: data.save || false,
      reasoning: "Human action from UI",
    }),
  });
  if (!response.ok) throw new Error("Action failed");
  return parseJson<GameState>(response);
}
