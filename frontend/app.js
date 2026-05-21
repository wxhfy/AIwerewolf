const dictionary = {
  zh: {
    pageTitle: "AI Werewolf 观战台",
    brand: "AI Werewolf",
    title: "观战台",
    subtitle: "离线 AI 狼人杀演示，可切换公开视角与主持视角。",
    seed: "Seed",
    run: "运行一局",
    private: "主持视角",
    public: "公开视角",
    winner: "胜者",
    day: "天数",
    phase: "阶段",
    events: "事件",
    players: "玩家",
    timeline: "事件时间线",
    statusReady: "已就绪",
    statusHint: "点击按钮生成一局新的 AI 对局。",
    statusLoading: "正在生成对局",
    statusLoaded: "对局已生成",
    statusLoadedDetail: "已载入第 {day} 天结束的完整事件流。",
    statusError: "加载失败",
    statusErrorDetail: "接口请求失败，请确认 FastAPI 服务正在运行。",
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
  },
  en: {
    pageTitle: "AI Werewolf Spectator",
    brand: "AI Werewolf",
    title: "Spectator Console",
    subtitle: "Offline AI werewolf demo with public and moderator views.",
    seed: "Seed",
    run: "Run Game",
    private: "Moderator View",
    public: "Public View",
    winner: "Winner",
    day: "Day",
    phase: "Phase",
    events: "Events",
    players: "Players",
    timeline: "Event Timeline",
    statusReady: "Ready",
    statusHint: "Generate a new AI match from the controls.",
    statusLoading: "Generating match",
    statusLoaded: "Match loaded",
    statusLoadedDetail: "Loaded a full event stream ending on day {day}.",
    statusError: "Load failed",
    statusErrorDetail: "API request failed. Confirm the FastAPI server is running.",
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
  },
};

const state = {
  showPrivate: false,
  lang: getInitialLang(),
  busy: false,
};

const els = {
  seed: document.querySelector("#seed"),
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
};

bindEvents();
applyLanguage();
runGame();

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
}

async function runGame() {
  setBusy(true);
  setStatus("loading", t("statusLoading"), t("statusHint"));
  setLoading();

  try {
    const seed = Number(els.seed.value || 7);
    const response = await fetch(`/api/games?seed=${seed}&show_private=${state.showPrivate}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const game = await response.json();
    render(game);
    setStatus("loaded", t("statusLoaded"), format(t("statusLoadedDetail"), { day: game.day }));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    renderError(message);
    setStatus("error", t("statusError"), `${t("statusErrorDetail")} (${message})`);
  } finally {
    setBusy(false);
  }
}

function setLanguage(lang) {
  state.lang = lang;
  const url = new URL(window.location.href);
  url.searchParams.set("lang", lang);
  window.history.replaceState({}, "", url);
  applyLanguage();
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
}

function setBusy(busy) {
  state.busy = busy;
  els.run.disabled = busy;
  els.private.disabled = busy;
  els.langZh.disabled = busy;
  els.langEn.disabled = busy;
}

function setLoading() {
  els.winner.textContent = "...";
  els.day.textContent = "...";
  els.phase.textContent = "...";
  els.eventCount.textContent = "...";
  els.players.innerHTML = "";
  els.timeline.innerHTML = "";
}

function render(game) {
  els.winner.textContent = label(game.winner);
  els.day.textContent = String(game.day);
  els.phase.textContent = game.phase;
  els.eventCount.textContent = String(game.events.length);
  els.players.innerHTML = game.players.map(renderPlayer).join("");
  els.timeline.innerHTML = game.events.map(renderEvent).join("");
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
  const eventLabel = event.visibility === "private" ? `${event.type} · ${t("privateTag")}` : event.type;
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

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
