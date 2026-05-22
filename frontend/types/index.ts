/**
 * 狼人杀游戏类型定义
 * 与后端 models.py 保持一致
 */

export enum Alignment {
  VILLAGE = "village",
  WOLF = "wolf",
}

export enum Role {
  VILLAGER = "Villager",
  WEREWOLF = "Werewolf",
  SEER = "Seer",
  WITCH = "Witch",
  HUNTER = "Hunter",
  GUARD = "Guard",
}

export enum Phase {
  SETUP = "SETUP",
  NIGHT_START = "NIGHT_START",
  NIGHT_GUARD_ACTION = "NIGHT_GUARD_ACTION",
  NIGHT_WOLF_ACTION = "NIGHT_WOLF_ACTION",
  NIGHT_WITCH_ACTION = "NIGHT_WITCH_ACTION",
  NIGHT_SEER_ACTION = "NIGHT_SEER_ACTION",
  NIGHT_RESOLVE = "NIGHT_RESOLVE",
  DAY_START = "DAY_START",
  DAY_SPEECH = "DAY_SPEECH",
  DAY_VOTE = "DAY_VOTE",
  DAY_RESOLVE = "DAY_RESOLVE",
  HUNTER_SHOOT = "HUNTER_SHOOT",
  GAME_END = "GAME_END",
}

export enum ActionType {
  TALK = "talk",
  VOTE = "vote",
  ATTACK = "attack",
  DIVINE = "divine",
  GUARD = "guard",
  WITCH_SAVE = "witch_save",
  WITCH_POISON = "witch_poison",
  SHOOT = "shoot",
  SKIP = "skip",
}

export enum EventType {
  GAME_START = "GAME_START",
  PHASE_CHANGED = "PHASE_CHANGED",
  PRIVATE_INFO = "PRIVATE_INFO",
  CHAT_MESSAGE = "CHAT_MESSAGE",
  NIGHT_ACTION = "NIGHT_ACTION",
  VOTE_CAST = "VOTE_CAST",
  PLAYER_DIED = "PLAYER_DIED",
  HUNTER_SHOT = "HUNTER_SHOT",
  SYSTEM_MESSAGE = "SYSTEM_MESSAGE",
  GAME_END = "GAME_END",
}

export interface Player {
  id: string;
  seat: number;
  name: string;
  role?: Role;
  alignment?: Alignment;
  alive: boolean;
  is_ai: boolean;
}

export interface GameEvent {
  id: string;
  ts: number;
  day: number;
  phase: string;
  type: string;
  visibility: string;
  visible_to: string[];
  payload: Record<string, any>;
}

export interface NightActions {
  guard_target_id?: string;
  last_guard_target_id?: string;
  wolf_votes: Record<string, string>;
  wolf_target_id?: string;
  witch_save: boolean;
  witch_poison_target_id?: string;
  seer_target_id?: string;
  seer_result?: Record<string, any>;
  deaths: Array<{ player_id: string; reason: string }>;
}

export interface GameState {
  id: string;
  phase: string;
  day: number;
  players: Player[];
  events: GameEvent[];
  votes: Record<string, string>;
  night_actions?: NightActions;
  daily_summaries: Record<number, string[]>;
  daily_summary_facts: Record<number, any[]>;
  winner?: Alignment;
  alive_count?: number;
  event_count?: number;
  last_event?: GameEvent;
}

export interface RoomRecord {
  id: string;
  name: string;
  seed: number;
  player_count: number;
  agent_type: string;
  status: string;
  created_at: number;
  updated_at: number;
  current_game_id?: string;
  game_history: string[];
  latest_snapshot?: GameState;
}

export interface RoomCreateRequest {
  name?: string;
  seed?: number;
  player_count?: number;
  agent_type?: string;
}

export type WebSocketMessage =
  | { type: "status"; status: string; seed?: number; agent_type?: string }
  | { type: "snapshot"; state: GameState; room_id?: string }
  | { type: "complete"; state?: GameState; room?: RoomRecord }
  | { type: "room"; room: RoomRecord }
  | { type: "error"; message: string };

export type WebSocketRequest = {
  action: "start";
  seed?: number;
  agent_type?: string;
  show_private?: boolean;
  delay_ms?: number;
};

export enum ViewMode {
  PUBLIC = "public",
  MODERATOR = "moderator",
}

export enum Language {
  ZH = "zh",
  EN = "en",
}

export enum AgentType {
  HEURISTIC = "heuristic",
  LLM = "llm",
}
