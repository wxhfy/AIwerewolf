import { AgentType, GameState, RoomCreateRequest, RoomLlmConfig, RoomRecord } from "@/types";
import { apiUrl } from "@/lib/api";

export type GameMode = "ai" | "human";

/** Free SiliconFlow turns can exceed 30s (night chain / speeches). */
const requestTimeoutMs = 180000;

interface CreateRoomParams {
  seed: number;
  playerCount: number;
  agentType: AgentType;
  mode: GameMode;
  humanSeat: number;
  llmConfig?: RoomLlmConfig;
}

interface HumanActionPayload {
  target_id?: string | null;
  speech?: string | null;
  save?: boolean;
}

export interface StartMatchResponse {
  match_id: string;
  room_id: string;
  status: "queued" | "running" | "completed" | "accepted" | "waiting_human";
  seq: number;
  snapshot: GameState;
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

export async function createRoom({ seed, playerCount, agentType, mode, humanSeat, llmConfig }: CreateRoomParams): Promise<RoomRecord> {
  const body: RoomCreateRequest = {
    name: "Demo Room",
    seed,
    player_count: playerCount,
    agent_type: agentType,
    ...(mode === "human" ? { human_seat: humanSeat } : {}),
    ...(llmConfig ? { llm_config: llmConfig } : {}),
  };

  const response = await fetchWithTimeout(apiUrl("/api/rooms"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Failed to create room (${response.status})`);
  return parseJson<RoomRecord>(response);
}

export async function prepareRoom(roomId: string, showPrivate = false): Promise<GameState> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/prepare?show_private=${showPrivate ? "true" : "false"}`), { method: "POST" });
  if (!response.ok) throw new Error(`Prepare failed (${response.status})`);
  return parseJson<GameState>(response);
}

export interface HumanActionResponse {
  status: "accepted" | "completed" | "running";
  match_id: string;
  room_id: string;
  seq: number;
  snapshot: GameState;
}

function unwrapStartPayload(body: any): StartMatchResponse {
  if (body && typeof body === "object" && body.snapshot && body.match_id) {
    return {
      match_id: String(body.match_id),
      room_id: String(body.room_id || ""),
      status: (body.status as StartMatchResponse["status"]) || "running",
      seq: Number(body.seq || 0),
      snapshot: body.snapshot as GameState,
    };
  }
  const snapshot = body as GameState;
  return {
    match_id: String(snapshot.id || ""),
    room_id: "",
    status: snapshot.winner ? "completed" : "running",
    seq: Number((snapshot as any).seq || 0),
    snapshot,
  };
}

export async function startRoom(roomId: string, showPrivate = false): Promise<StartMatchResponse> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/start?show_private=${showPrivate ? "true" : "false"}`), { method: "POST" });
  // Human rooms return 202 (accepted, continue via SSE); AI rooms return 200.
  if (!response.ok && response.status !== 202) throw new Error(`Start failed (${response.status})`);
  return unwrapStartPayload(await parseJson<any>(response));
}

export async function startAiMatch(roomId: string, showPrivate = false): Promise<StartMatchResponse> {
  const response = await fetchWithTimeout(
    apiUrl(`/api/rooms/${roomId}/start?show_private=${showPrivate ? "true" : "false"}`),
    { method: "POST" },
  );
  if (!response.ok) throw new Error(`Start failed (${response.status})`);
  return parseJson<StartMatchResponse>(response);
}

export async function fetchRoom(roomId: string): Promise<RoomRecord | null> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}`));
  if (!response.ok) return null;
  return parseJson<RoomRecord>(response);
}

export async function fetchReplayDownload(gameId: string, showPrivate = false): Promise<Record<string, unknown>> {
  const params = new URLSearchParams({
    show_private: showPrivate ? "true" : "false",
    download: "false",
  });
  const response = await fetchWithTimeout(apiUrl(`/api/replay/${gameId}.json?${params.toString()}`));
  if (!response.ok) throw new Error(`Replay export failed (${response.status})`);
  return parseJson<Record<string, unknown>>(response);
}

export async function submitHumanAction(roomId: string, data: HumanActionPayload): Promise<HumanActionResponse> {
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
  // Async human continuation returns 202 Accepted.
  if (!response.ok && response.status !== 202) throw new Error("Action failed");
  const body = await parseJson<any>(response);
  if (body && body.snapshot && body.match_id) {
    return {
      status: (body.status as HumanActionResponse["status"]) || "accepted",
      match_id: String(body.match_id),
      room_id: String(body.room_id || roomId),
      seq: Number(body.seq || 0),
      snapshot: body.snapshot as GameState,
    };
  }
  // Backward-compatible: older servers returned the snapshot directly.
  const snapshot = body as GameState;
  return {
    status: snapshot.winner ? "completed" : "accepted",
    match_id: String(snapshot.id || ""),
    room_id: roomId,
    seq: Number((snapshot as any).seq || 0),
    snapshot,
  };
}

export async function pauseRoom(roomId: string): Promise<{ paused: boolean; status: string }> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/pause`), { method: "POST" });
  if (!response.ok) throw new Error(`Pause failed (${response.status})`);
  return parseJson<{ paused: boolean; status: string }>(response);
}

export async function resumeRoom(roomId: string): Promise<{ paused: boolean; status: string }> {
  const response = await fetchWithTimeout(apiUrl(`/api/rooms/${roomId}/resume`), { method: "POST" });
  if (!response.ok) throw new Error(`Resume failed (${response.status})`);
  return parseJson<{ paused: boolean; status: string }>(response);
}
