import { Language } from "@/types";

/**
 * 国际化文本字典
 */
const translations = {
  [Language.ZH]: {
    pageTitle: "AI 狼人杀",
    brand: "AI Werewolf",
    title: "观战台",
    subtitle: "实时房间观战控制台，可切换公开视角与主持视角，并按阶段查看 AI 对局推进。",
    agentType: "Agent",
    agentMode: "Agent 模式",
    agentHeuristic: "启发式",
    agentLlm: "LLM",
    agentDescription: "启发式模式用于稳定回归；LLM 模式会走 .env 中配置的模型，便于做多 Agent 对战和复盘实验。",
    seed: "Seed",
    speed: "速度",
    run: "运行一局",
    private: "主持视角",
    public: "公开视角",
    publicMode: "公开视角",
    winner: "胜者",
    day: "天数",
    phase: "阶段",
    events: "事件",
    players: "玩家席位",
    timeline: "事件时间线",
    controlPanel: "对局控制",
    runtimeStatus: "运行状态",
    latestEvent: "最新事件",
    aliveCount: "存活人数",
    viewMode: "视角",
    boardHint: "实时刷新当前存活与身份状态",
    timelineHint: "按阶段追加事件和公开发言",
    observerNotes: "观战说明",
    dailySummary: "当日摘要",
    roomDescription: "每个房间会保留当前对局和历史对局编号，方便后续扩展成多人房间系统。",
    viewDescription: "公开视角隐藏身份；主持视角直接揭示角色与阵营，用于调试和复盘。",
    streamingLabel: "实时流",
    streamingDescription: "页面通过 WebSocket 接收快照，不是整局结束后再一次性渲染。",
    statusReady: "已就绪",
    statusHint: "点击按钮生成一局新的 AI 对局。",
    statusLoading: "正在生成对局",
    statusStreaming: "对局进行中",
    statusLoaded: "对局已生成",
    statusStreamingDetail: "已推进到第 {day} 天 {phase}，累计 {events} 条事件。",
    statusLoadedDetail: "已载入第 {day} 天结束的完整事件流。",
    statusError: "加载失败",
    statusErrorDetail: "接口请求失败，请确认 FastAPI 服务正在运行。",
    roomLabel: "房间",
    gameLabel: "游戏",
    roomReady: "房间已创建",
    roomReadyDetail: "当前房间 {roomId}，Agent={agentType}，可以直接开始新的 AI 对局。",
    hiddenRole: "身份隐藏",
    alive: "存活",
    dead: "出局",
    privateTag: "私密",
    village: "好人阵营",
    wolf: "狼人阵营",
    none: "无",
    phaseChanged: "阶段切换为 {phase}。",
    voted: "{voter} 投给了 {target}。{reasoning}",
    died: "{player} 因 {reason} 出局。",
    wins: "{winner} 获胜（{reason}）。",
    action: "{actor} 执行了 {action} -> {target}。{reasoning}",
    errorPrefix: "错误",

    lobby: "大厅",
    createRoom: "创建房间",
    joinRoom: "加入房间",
    settings: "设置",
    personalCenter: "个人中心",
    enterGame: "进入游戏",
    lobbyDescription: "选择房间加入，或创建新房间开始游戏。",
    backToLobby: "返回大厅",
    lobbyTitle: "游戏大厅",

    room: "房间",
    roomName: "房间名称",
    prepare: "准备",
    ready: "已准备",
    startGame: "开始游戏",
    gameSettings: "游戏设置",
    roomSettings: "房间设置",
    backToRoom: "返回房间",
    roomTitle: "房间准备",

    game: "游戏",
    leaveGame: "离开游戏",
    replay: "复盘",
    watchGame: "观战",
    playerList: "玩家列表",
    messageInput: "输入消息...",
    sendMessage: "发送",
    skillAction: "请行动",
    gameTitle: "游戏对局",
    nightPhase: "夜晚",
    dayPhase: "白天",
    votePhase: "投票",

    settlement: "结算",
    playAgain: "再来一局",
    identityReveal: "身份揭晓",
    settlementTitle: "游戏结束",
    gameStats: "游戏统计",
    totalDays: "总天数",
    winnerSide: "获胜方",

    roles: {
      Villager: "村民",
      Werewolf: "狼人",
      Seer: "预言家",
      Witch: "女巫",
      Hunter: "猎人",
      Guard: "守卫",
    },
    phases: {
      SETUP: "准备中",
      NIGHT_START: "夜幕降临",
      NIGHT_GUARD_ACTION: "守卫行动",
      NIGHT_WOLF_ACTION: "狼人行动",
      NIGHT_WITCH_ACTION: "女巫行动",
      NIGHT_SEER_ACTION: "预言家行动",
      NIGHT_RESOLVE: "黑夜结算",
      DAY_START: "天亮了",
      DAY_SPEECH: "自由发言",
      DAY_VOTE: "投票放逐",
      DAY_RESOLVE: "投票结算",
      HUNTER_SHOOT: "猎人开枪",
      GAME_END: "游戏结束",
    },
  },
  [Language.EN]: {
    pageTitle: "AI Werewolf Spectator",
    brand: "AI Werewolf",
    title: "Spectator Console",
    subtitle: "Live room console for AI werewolf matches with public and moderator perspectives.",
    agentType: "Agent",
    agentMode: "Agent Mode",
    agentHeuristic: "Heuristic",
    agentLlm: "LLM",
    agentDescription: "Heuristic mode is for stable regression. LLM mode uses the model configured in .env for multi-agent experiments and replay analysis.",
    seed: "Seed",
    speed: "Speed",
    run: "Run Game",
    private: "Moderator View",
    public: "Public View",
    publicMode: "Public View",
    winner: "Winner",
    day: "Day",
    phase: "Phase",
    events: "Events",
    players: "Player Seats",
    timeline: "Event Timeline",
    controlPanel: "Match Controls",
    runtimeStatus: "Runtime Status",
    latestEvent: "Latest Event",
    aliveCount: "Alive Count",
    viewMode: "View",
    boardHint: "Live seats, life state, and role visibility",
    timelineHint: "Phase-by-phase event and speech stream",
    observerNotes: "Observer Notes",
    dailySummary: "Day Summary",
    roomDescription: "Each room keeps the current game id and history so the app can grow into a multiplayer room system.",
    viewDescription: "Public view hides roles. Moderator view reveals role and alignment for debugging and replay.",
    streamingLabel: "Streaming",
    streamingDescription: "The page renders from WebSocket snapshots instead of waiting for the whole match to finish.",
    statusReady: "Ready",
    statusHint: "Generate a new AI match from the controls.",
    statusLoading: "Generating match",
    statusStreaming: "Match in progress",
    statusLoaded: "Match loaded",
    statusStreamingDetail: "Advanced to day {day} {phase} with {events} events.",
    statusLoadedDetail: "Loaded a full event stream ending on day {day}.",
    statusError: "Load failed",
    statusErrorDetail: "API request failed. Confirm the FastAPI server is running.",
    roomLabel: "Room",
    gameLabel: "Game",
    roomReady: "Room ready",
    roomReadyDetail: "Current room {roomId}, Agent={agentType}. You can start a new AI match now.",
    hiddenRole: "Role hidden",
    alive: "Alive",
    dead: "Out",
    privateTag: "private",
    village: "Village",
    wolf: "Wolves",
    none: "none",
    phaseChanged: "Phase changed to {phase}.",
    voted: "{voter} voted for {target}. {reasoning}",
    died: "{player} died by {reason}.",
    wins: "{winner} wins ({reason}).",
    action: "{actor} chose {action} -> {target}. {reasoning}",
    errorPrefix: "ERROR",

    lobby: "Lobby",
    createRoom: "Create Room",
    joinRoom: "Join Room",
    settings: "Settings",
    personalCenter: "Personal Center",
    enterGame: "Enter Game",
    lobbyDescription: "Select a room to join, or create a new room to start playing.",
    backToLobby: "Back to Lobby",
    lobbyTitle: "Game Lobby",

    room: "Room",
    roomName: "Room Name",
    prepare: "Prepare",
    ready: "Ready",
    startGame: "Start Game",
    gameSettings: "Game Settings",
    roomSettings: "Room Settings",
    backToRoom: "Back to Room",
    roomTitle: "Room Preparation",

    game: "Game",
    leaveGame: "Leave Game",
    replay: "Replay",
    watchGame: "Watch",
    playerList: "Players",
    messageInput: "Type a message...",
    sendMessage: "Send",
    skillAction: "Please act",
    gameTitle: "Game Match",
    nightPhase: "Night",
    dayPhase: "Day",
    votePhase: "Vote",

    settlement: "Settlement",
    playAgain: "Play Again",
    identityReveal: "Identity Reveal",
    settlementTitle: "Game Over",
    gameStats: "Game Statistics",
    totalDays: "Total Days",
    winnerSide: "Winning Side",

    roles: {
      Villager: "Villager",
      Werewolf: "Werewolf",
      Seer: "Seer",
      Witch: "Witch",
      Hunter: "Hunter",
      Guard: "Guard",
    },
    phases: {
      SETUP: "Setup",
      NIGHT_START: "Night Falls",
      NIGHT_GUARD_ACTION: "Guard Action",
      NIGHT_WOLF_ACTION: "Wolf Action",
      NIGHT_WITCH_ACTION: "Witch Action",
      NIGHT_SEER_ACTION: "Seer Action",
      NIGHT_RESOLVE: "Night Resolve",
      DAY_START: "Day Breaks",
      DAY_SPEECH: "Free Speech",
      DAY_VOTE: "Vote Exile",
      DAY_RESOLVE: "Vote Resolve",
      HUNTER_SHOOT: "Hunter Shoots",
      GAME_END: "Game End",
    },
  },
};

type Translations = typeof translations[Language.ZH];

/**
 * 获取翻译文本
 */
export function t(key: keyof Translations, lang: Language = Language.ZH): string {
  return translations[lang][key] || key;
}

/**
 * 格式化带参数的翻译文本
 */
export function format(
  template: string,
  values: Record<string, string | number>
): string {
  let result = template;
  Object.keys(values).forEach((key) => {
    result = result.split(`{${key}}`).join(String(values[key]));
  });
  return result;
}

/**
 * 获取角色名称的翻译
 */
export function tRole(role: string, lang: Language = Language.ZH): string {
  const roles = translations[lang].roles;
  return (roles as any)[role] || role;
}

/**
 * 获取阶段名称的翻译
 */
export function tPhase(phase: string, lang: Language = Language.ZH): string {
  const phases = translations[lang].phases;
  return (phases as any)[phase] || phase;
}
