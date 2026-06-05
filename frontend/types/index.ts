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
  WHITE_WOLF_KING = "WhiteWolfKing",
  SEER = "Seer",
  WITCH = "Witch",
  HUNTER = "Hunter",
  GUARD = "Guard",
  IDIOT = "Idiot",
  // Template roles — mirror backend Role enum (engine/models.py). Marked
  // `playable=False` in the backend registry; not yet selectable by the
  // 7-12P configs. Added here so future roster-preview UIs / role-pack
  // selectors can already filter by these values.
  CUPID = "Cupid",
  BIG_BAD_WOLF = "BigBadWolf",
  WOLF_CUB = "WolfCub",
  WOLF_KING = "WolfKing",
  KNIGHT = "Knight",
  ELDER = "Elder",
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
  DAY_BADGE_SIGNUP = "DAY_BADGE_SIGNUP",
  DAY_BADGE_SPEECH = "DAY_BADGE_SPEECH",
  DAY_BADGE_ELECTION = "DAY_BADGE_ELECTION",
  DAY_PK_SPEECH = "DAY_PK_SPEECH",
  DAY_LAST_WORDS = "DAY_LAST_WORDS",
  DAY_SPEECH = "DAY_SPEECH",
  DAY_VOTE = "DAY_VOTE",
  DAY_RESOLVE = "DAY_RESOLVE",
  BADGE_TRANSFER = "BADGE_TRANSFER",
  HUNTER_SHOOT = "HUNTER_SHOOT",
  WHITE_WOLF_KING_BOOM = "WHITE_WOLF_KING_BOOM",
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
  BOOM = "boom",
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
  WHITE_WOLF_KING_BOOM = "WHITE_WOLF_KING_BOOM",
  SYSTEM_MESSAGE = "SYSTEM_MESSAGE",
  GAME_END = "GAME_END",
}

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonRecord = Record<string, JsonValue>;

export interface Persona {
  style_label?: string;
  mbti?: string;
  basic_info?: string;
}

export interface Player {
  id: string;
  seat: number;
  name: string;
  role?: Role;
  alignment?: Alignment;
  alive: boolean;
  is_ai: boolean;
  agent_type?: string;
  persona?: Persona | null;
  portraitId?: number;
}

export interface EventPayload {
  actor_id?: string;
  actor_name?: string;
  action_type?: string;
  message?: string;
  phase?: string;
  player_name?: string;
  reason?: string;
  reasoning?: string;
  speech?: string;
  target?: { id?: string; name?: string };
  target_id?: string;
  target_name?: string;
  voter_name?: string;
  winner?: Alignment | string;
}

export interface GameEvent {
  id: string;
  ts: number;
  day: number;
  phase: string;
  type: EventType;
  visibility: "public" | "private" | string;
  visible_to: string[];
  payload: EventPayload;
}

export interface NightActions {
  guard_target_id?: string;
  last_guard_target_id?: string;
  wolf_votes: Record<string, string>;
  wolf_target_id?: string;
  witch_save: boolean;
  witch_poison_target_id?: string;
  seer_target_id?: string;
  seer_result?: JsonRecord;
  deaths: Array<{ player_id: string; reason: string }>;
}

export interface BadgeState {
  holder_id?: string | null;
  candidates: string[];
  signup: Record<string, boolean>;
  votes: Record<string, string>;
  history: Record<number, Record<string, string>>;
  revote_count: number;
}

export interface RoleAbilities {
  witch_heal_used: boolean;
  witch_poison_used: boolean;
  hunter_can_shoot: boolean;
  idiot_revealed: boolean;
  white_wolf_king_boom_used: boolean;
}

export interface PendingInputOption {
  id: string;
  name?: string;
  seat?: number;
  alive?: boolean;
}

export interface PendingInput {
  player_id: string;
  player_name: string;
  seat: number;
  request: string;
  phase: string;
  action_type: string;
  prompt: string;
  options: PendingInputOption[];
  can_skip: boolean;
  placeholder?: string | null;
}

export interface GameState {
  id: string;
  phase: string;
  day: number;
  players: Player[];
  events: GameEvent[];
  votes: Record<string, string>;
  vote_history: Record<number, Record<string, string>>;
  day_history: Record<number, JsonRecord>;
  badge?: BadgeState;
  night_actions?: NightActions;
  role_abilities?: RoleAbilities;
  current_speaker_id?: string | null;
  pk_targets?: string[];
  pk_source?: string | null;
  pending_input?: PendingInput | null;
  phase_cursor?: JsonRecord;
  decision_records?: JsonRecord[];
  daily_summaries: Record<number, string[]>;
  daily_summary_facts: Record<number, JsonValue[]>;
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

export type PrepareSnapshot = GameState;

export interface RoomInfoRow {
  label: string;
  value: string;
}

export interface RoomCreateRequest {
  name?: string;
  seed?: number;
  player_count?: number;
  agent_type?: string;
}

export interface ValidationIssue {
  issue_id: string;
  severity: string;
  gate: string;
  issue_type: string;
  location: Record<string, any>;
  message: string;
  evidence: string[];
  required_fix: string;
  repair_tool?: string | null;
  blocking: boolean;
}

export interface ValidationResult {
  report_id: string;
  game_id: string;
  passed: boolean;
  grade: string;
  score: number;
  issues: ValidationIssue[];
  required_tools: string[];
  revision_instructions: string[];
  publish_allowed: boolean;
}

export interface TrackBReviewDocument {
  report_id: string;
  game_id: string;
  status: string;
  view_scope: string;
  grade: string;
  score: number;
  publish_allowed: boolean;
  review_report: Record<string, any>;
  markdown: string;
  validation_result: ValidationResult;
  replay_bundle: Record<string, any>;
  speech_acts: Array<Record<string, any>>;
  suspicion_matrix: Array<Record<string, any>>;
  repair_history: Array<Record<string, any>>;
  html_report?: string | null;
  metadata: Record<string, any>;
  created_at?: string | null;
  published_at?: string | null;
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
