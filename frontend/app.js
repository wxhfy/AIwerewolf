const dictionary = {
  zh: {
    pageTitle: "AI Werewolf 观战台",
    brand: "AI Werewolf",
    title: "观战台",
    subtitleShort: "The Shadow Match",
    subtitle: "实时房间观战控制台，可切换公开视角与主持视角，并按阶段查看 AI 对局推进。",
    welcomeBadge: "对局誓约",
    welcomeKicker: "Live Room Protocol",
    heroTitle: "在谎言与真相之间，启动一局 AI 狼人杀。",
    heroBody:
      "这不是离线回放页，而是一张实时运行的房间契约。你可以选择 Agent、切换主持视角，并沿着阶段流观察每个角色如何发言、投票、伪装与出局。",
    oathText: "当夜幕降临，身份将被隐藏；当白昼升起，每一句发言都会进入审判记录。",
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
    liveTable: "实时牌桌",
    timelineHint: "按阶段追加事件和公开发言",
    observerNotes: "观战说明",
    notesHint: "房间、摘要和回放入口",
    dailySummary: "当日摘要",
    roomHistory: "房间历史",
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
    gameLabel: "对局",
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
    sourceLlm: "LLM",
    sourceFallback: "回退",
  },
  en: {
    pageTitle: "AI Werewolf Spectator",
    brand: "AI Werewolf",
    title: "Spectator Console",
    subtitleShort: "The Shadow Match",
    subtitle: "Live room console for AI werewolf matches with public and moderator perspectives.",
    welcomeBadge: "Match Oath",
    welcomeKicker: "Live Room Protocol",
    heroTitle: "Start an AI werewolf match between lies and judgment.",
    heroBody:
      "This is not a static replay page. It is a live room contract where you can switch agents, reveal moderator view, and watch speeches, votes, deception, and eliminations phase by phase.",
    oathText: "When night falls, identities are concealed. When dawn returns, every statement enters the record.",
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
    liveTable: "Live Table",
    timelineHint: "Phase-by-phase event and speech stream",
    observerNotes: "Observer Notes",
    notesHint: "Room, summaries, and replay hooks",
    dailySummary: "Day Summary",
    roomHistory: "Room History",
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
    roomReadyDetail: "Current room {roomId}, agent={agentType}. You can start a new AI match now.",
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
    wins: "{winner} win ({reason}).",
    action: "{actor} chose {action} -> {target}. {reasoning}",
    errorPrefix: "ERROR",
    sourceLlm: "LLM",
    sourceFallback: "fallback",
  },
};

const state = {
  showPrivate: false,
  lang: getInitialLang(),
  busy: false,
  roomId: null,
  gameId: null,
  agentType: getInitialAgentType(),
  lastSnapshot: null,
};

const els = {
  seed: document.querySelector("#seed"),
  speed: document.querySelector("#speed"),
  agentType: document.querySelector("#agent-type"),
  run: document.querySelector("#run"),
  private: document.querySelector("#private"),
  langZh: document.querySelector("#lang-zh"),
  langEn: document.querySelector("#lang-en"),
  winner: document.querySelector("#winner"),
  day: document.querySelector("#day"),
  phase: document.querySelector("#phase"),
  eventCount: document.querySelector("#event-count"),
  players: document.querySelector("#players"),
  timeline: document.querySelector("#timeline"),
  statusBar: document.querySelector(".statusbar"),
  statusTitle: document.querySelector("#status-title"),
  statusText: document.querySelector("#status-text"),
  roomLabel: document.querySelector("#room-label"),
  gameLabel: document.querySelector("#game-label"),
  viewLabel: document.querySelector("#view-label"),
  viewMode: document.querySelector("#view-mode"),
  lastEventTitle: document.querySelector("#last-event-title"),
  lastEventText: document.querySelector("#last-event-text"),
  aliveCount: document.querySelector("#alive-count"),
  agentMode: document.querySelector("#agent-mode"),
  dailySummary: document.querySelector("#daily-summary"),
  roomHistory: document.querySelector("#room-history"),
};

bindEvents();
applyLanguage();
bootstrap();

function bindEvents() {
  els.run.addEventListener("click", async () => {
    await runGame();
  });

  els.private.addEventListener("click", async () => {
    state.showPrivate = !state.showPrivate;
    applyLanguage();
    await runGame();
  });

  els.langZh.addEventListener("click", () => setLanguage("zh"));
  els.langEn.addEventListener("click", () => setLanguage("en"));
  els.agentType.addEventListener("change", () => setAgentType(els.agentType.value));
}

async function runGame(retryOnRoomLost = true) {
  setBusy(true);
  setStatus("loading", t("statusLoading"), t("statusHint"));
  setLoading();

  try {
    await ensureRoom();
    const game = await runGameViaWebSocket();
    render(game);
    setStatus("loaded", t("statusLoaded"), format(t("statusLoadedDetail"), { day: game.day }));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // If room was lost (server restart), auto-retry once
    if (retryOnRoomLost && message.includes("Room not found")) {
      state.roomId = null;
      state.gameId = null;
      const url = new URL(window.location.href);
      url.searchParams.delete("room");
      window.history.replaceState({}, "", url);
      return runGame(false); // retry exactly once
    }
    renderError(message);
    setStatus("error", t("statusError"), `${t("statusErrorDetail")} (${message})`);
  } finally {
    setBusy(false);
  }
}

async function bootstrap() {
  try {
    await ensureRoom();
    setStatus(
      "loaded",
      t("roomReady"),
      format(t("roomReadyDetail"), { roomId: shortId(state.roomId), agentType: agentTypeLabel(state.agentType) })
    );
    await refreshRoomHistory();
    updateMeta();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus("error", t("statusError"), `${t("statusErrorDetail")} (${message})`);
    renderError(message);
  }
}

async function ensureRoom() {
  // Try URL-cached room first — validate it still exists on server
  const roomIdFromUrl = new URL(window.location.href).searchParams.get("room");
  if (roomIdFromUrl) {
    try {
      const check = await fetch(`/api/rooms/${roomIdFromUrl}`, { headers: { Accept: "application/json" } });
      if (check.ok) {
        const room = await check.json();
        state.roomId = room.id;
        if (room.agent_type) {
          state.agentType = room.agent_type;
        }
        await refreshRoomHistory();
        updateMeta();
        syncControls();
        return state.roomId;
      }
    } catch (e) {
      // Server restarted, room is gone — create a new one below
    }
    // Stale room ID: clear from URL and state
    state.roomId = null;
    state.gameId = null;
    const url = new URL(window.location.href);
    url.searchParams.delete("room");
    window.history.replaceState({}, "", url);
  }

  if (state.roomId) {
    // Already validated above or previously created
    return state.roomId;
  }

  const seed = Number(els.seed.value || 7);
  const response = await fetch(
    `/api/rooms?name=${encodeURIComponent("Demo Room")}&seed=${seed}&player_count=7&agent_type=${encodeURIComponent(state.agentType)}`,
    {
      method: "POST",
      headers: { Accept: "application/json" },
    }
  );
  if (!response.ok) {
    throw new Error(`Failed to create room: HTTP ${response.status}`);
  }
  const room = await response.json();
  state.roomId = room.id;
  state.agentType = room.agent_type || state.agentType;
  const url = new URL(window.location.href);
  url.searchParams.set("room", room.id);
  window.history.replaceState({}, "", url);
  syncControls();
  await refreshRoomHistory();
  updateMeta();
  return state.roomId;
}

async function runGameViaWebSocket() {
  if (!state.roomId) {
    throw new Error("Room is not initialized");
  }
  const seed = Number(els.seed.value || 7);
  const delayMs = Number(els.speed.value || 80);
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws/rooms/${state.roomId}`);

  return new Promise((resolve, reject) => {
    let finalState = null;

    socket.addEventListener("open", () => {
      socket.send(
        JSON.stringify({
          action: "start",
          seed,
          agent_type: state.agentType,
          show_private: state.showPrivate,
          delay_ms: delayMs,
        })
      );
    });

    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "error") {
        socket.close();
        reject(new Error(payload.message));
        return;
      }
      if (payload.type === "room" && payload.room) {
        state.roomId = payload.room.id;
        state.agentType = payload.room.agent_type || state.agentType;
        updateMeta(payload.room.current_game_id || state.gameId);
        syncControls();
      }
      if (payload.type === "snapshot" && payload.state) {
        finalState = payload.state;
        state.gameId = payload.state.id;
        render(payload.state);
        updateMeta(payload.state.id);
        setStatus(
          "loading",
          t("statusStreaming"),
          format(t("statusStreamingDetail"), {
            day: payload.state.day,
            phase: payload.state.phase,
            events: payload.state.event_count,
          })
        );
      }
      if (payload.type === "complete") {
        finalState = payload.state || finalState;
        if (payload.room) {
          state.roomId = payload.room.id;
          state.gameId = payload.room.current_game_id || state.gameId;
          state.agentType = payload.room.agent_type || state.agentType;
        }
        refreshRoomHistory();
        updateMeta(state.gameId);
        syncControls();
        socket.close();
        if (finalState) {
          resolve(finalState);
        } else {
          reject(new Error("No final game state received"));
        }
      }
    });

    socket.addEventListener("error", () => {
      reject(new Error("WebSocket connection failed"));
    });

    socket.addEventListener("close", () => {
      if (!finalState) {
        reject(new Error("WebSocket closed before match completed"));
      }
    });
  });
}

function setLanguage(lang) {
  state.lang = lang;
  const url = new URL(window.location.href);
  url.searchParams.set("lang", lang);
  window.history.replaceState({}, "", url);
  applyLanguage();
  // Re-render dynamic game content with new language
  if (state.lastSnapshot) {
    render(state.lastSnapshot);
  }
}

function setAgentType(agentType) {
  state.agentType = agentType === "llm" ? "llm" : "heuristic";
  const url = new URL(window.location.href);
  url.searchParams.set("agent_type", state.agentType);
  window.history.replaceState({}, "", url);
  syncControls();
  updateMeta();
}

function applyLanguage() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = t("pageTitle");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    node.textContent = t(key);
  });
  els.private.textContent = state.showPrivate ? t("public") : t("private");
  els.langZh.classList.toggle("active", state.lang === "zh");
  els.langEn.classList.toggle("active", state.lang === "en");
  syncControls();
  if (els.viewLabel) {
    els.viewLabel.textContent = state.showPrivate ? t("private") : t("publicMode");
  }
  if (els.viewMode) {
    els.viewMode.textContent = state.showPrivate ? t("private") : t("publicMode");
  }
  updateMeta();
}

function setBusy(busy) {
  state.busy = busy;
  els.run.disabled = busy;
  els.private.disabled = busy;
  els.agentType.disabled = busy;
}

function setLoading() {
  els.winner.textContent = "...";
  els.day.textContent = "...";
  els.phase.textContent = "...";
  els.eventCount.textContent = "...";
  els.players.innerHTML = "";
  els.timeline.innerHTML = "";
  if (els.lastEventTitle) els.lastEventTitle.textContent = "...";
  if (els.lastEventText) els.lastEventText.textContent = "...";
  if (els.aliveCount) els.aliveCount.textContent = "...";
  if (els.dailySummary) els.dailySummary.textContent = "...";
}

function render(game) {
  state.lastSnapshot = game;
  state.gameId = game.id || state.gameId;
  els.winner.textContent = label(game.winner);
  els.day.textContent = String(game.day);
  els.phase.textContent = game.phase;
  els.eventCount.textContent = String(game.events.length);
  els.players.innerHTML = game.players.map(renderPlayer).join("");
  els.timeline.innerHTML = [...game.events].reverse().map(renderEvent).join("");
  els.timeline.scrollTop = 0;  // keep newest events visible at top
  if (els.aliveCount) {
    const alive = game.alive_count ?? game.players.filter((player) => player.alive).length;
    els.aliveCount.textContent = String(alive);
  }
  if (els.agentMode) {
    els.agentMode.textContent = agentTypeLabel(state.agentType);
  }
  if (els.lastEventTitle || els.lastEventText) {
    const latest = game.last_event || (game.events.length ? game.events[game.events.length - 1] : null);
    if (latest) {
      if (els.lastEventTitle) {
        els.lastEventTitle.textContent = latest.type;
      }
      if (els.lastEventText) {
        els.lastEventText.textContent = eventText(latest.type, latest.payload || {});
      }
    } else {
      if (els.lastEventTitle) els.lastEventTitle.textContent = "-";
      if (els.lastEventText) els.lastEventText.textContent = "-";
    }
  }
  if (els.dailySummary) {
    const lines = (game.daily_summaries && game.daily_summaries[game.day]) || [];
    if (lines.length) {
      els.dailySummary.innerHTML = lines
        .slice(-5)
        .map((line) => `<div class="summary-line">${escapeHtml(line)}</div>`)
        .join("");
    } else {
      els.dailySummary.textContent = "-";
    }
  }
  updateMeta();
}

async function refreshRoomHistory() {
  if (!state.roomId || !els.roomHistory) {
    return;
  }
  try {
    const response = await fetch(`/api/rooms/${state.roomId}/games`, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const games = await response.json();
    renderRoomHistory(games);
  } catch {
    els.roomHistory.textContent = "-";
  }
}

function renderRoomHistory(games) {
  if (!els.roomHistory) {
    return;
  }
  if (!games.length) {
    els.roomHistory.textContent = "-";
    return;
  }
  els.roomHistory.innerHTML = games
    .slice()
    .reverse()
    .slice(0, 6)
    .map(
      (game) => `
        <div class="history-item">
          <strong>${escapeHtml(shortId(game.id))}</strong>
          <div>${escapeHtml(`${t("day")} ${game.day} · ${game.phase} · ${label(game.winner)}`)}</div>
        </div>
      `
    )
    .join("");
}

function renderPlayer(player) {
  const role = player.role ? `${player.role} / ${player.alignment}` : t("hiddenRole");
  const alive = player.alive ? t("alive") : t("dead");
  return `
    <article class="player ${player.alive ? "" : "dead"}">
      <div class="seat">${player.seat}</div>
      <div>
        <div class="name">${escapeHtml(player.name)}</div>
        <div class="role">${escapeHtml(role)}</div>
      </div>
      <div class="state">${escapeHtml(alive)}</div>
    </article>
  `;
}

function renderEvent(event) {
  const payload = event.payload || {};
  const sourceTag = payload.agent_source === "llm" ? t("sourceLlm") : payload.agent_fallback ? t("sourceFallback") : "";
  const privateTag = event.visibility === "private" ? t("privateTag") : "";
  const parts = [event.type, privateTag, sourceTag].filter(Boolean);
  const eventLabel = parts.join(" · ");
  return `
    <article class="event">
      <div class="badge">D${event.day}<br>${escapeHtml(event.phase)}</div>
      <div>
        <strong>${escapeHtml(eventLabel)}</strong>
        <p>${escapeHtml(eventText(event.type, payload))}</p>
      </div>
    </article>
  `;
}

function renderError(message) {
  els.timeline.innerHTML = `
    <article class="event">
      <div class="badge">ERR</div>
      <div>
        <strong>${escapeHtml(t("errorPrefix"))}</strong>
        <p>${escapeHtml(message)}</p>
      </div>
    </article>
  `;
}

function eventText(type, payload) {
  if (payload.message) return payload.message;
  if (type === "CHAT_MESSAGE") return `${payload.actor_name}: ${payload.speech}`;
  if (type === "VOTE_CAST") {
    return format(t("voted"), {
      voter: payload.voter_name,
      target: payload.target_name,
      reasoning: payload.reasoning || "",
    }).trim();
  }
  if (type === "PLAYER_DIED") {
    return format(t("died"), { player: payload.player_name, reason: payload.reason });
  }
  if (type === "GAME_END") {
    return format(t("wins"), { winner: label(payload.winner), reason: payload.reason });
  }
  if (type === "NIGHT_ACTION") {
    const target = payload.target ? payload.target.name : payload.target_id || t("none");
    return format(t("action"), {
      actor: payload.actor_name,
      action: payload.action_type,
      target,
      reasoning: payload.reasoning || "",
    }).trim();
  }
  if (type === "PHASE_CHANGED") return format(t("phaseChanged"), { phase: payload.phase });
  return JSON.stringify(payload);
}

function label(value) {
  if (value === "village") return t("village");
  if (value === "wolf") return t("wolf");
  return value || "-";
}

function setStatus(mode, title, text) {
  els.statusBar.classList.remove("error", "loading");
  if (mode === "error") els.statusBar.classList.add("error");
  if (mode === "loading") els.statusBar.classList.add("loading");
  els.statusTitle.textContent = title;
  els.statusText.textContent = text;
}

function updateMeta() {
  els.roomLabel.textContent = `${t("roomLabel")}: ${shortId(state.roomId)}`;
  els.gameLabel.textContent = `${t("gameLabel")}: ${shortId(state.gameId)}`;
  if (els.agentMode) {
    els.agentMode.textContent = agentTypeLabel(state.agentType);
  }
}

function syncControls() {
  if (els.agentType) {
    els.agentType.value = state.agentType;
    const options = Array.from(els.agentType.options || []);
    options.forEach((option) => {
      const key = option.value === "llm" ? "agentLlm" : "agentHeuristic";
      option.textContent = t(key);
    });
  }
}

function t(key) {
  return dictionary[state.lang][key] || key;
}

function format(template, values) {
  let text = template;
  Object.keys(values).forEach((key) => {
    text = text.split(`{${key}}`).join(String(values[key]));
  });
  return text;
}

function getInitialLang() {
  const url = new URL(window.location.href);
  const lang = url.searchParams.get("lang");
  if (lang === "en" || lang === "zh") return lang;
  return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

function getInitialAgentType() {
  const url = new URL(window.location.href);
  return url.searchParams.get("agent_type") === "llm" ? "llm" : "heuristic";
}

function agentTypeLabel(value) {
  return value === "llm" ? t("agentLlm") : t("agentHeuristic");
}

function shortId(value) {
  if (!value) return "-";
  return String(value).slice(0, 8);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
