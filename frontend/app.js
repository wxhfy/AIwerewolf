const I18N = {
  zh: {
    run: "开始游戏",
    private: "主持视角",
    public: "公开视角",
    winner: "胜者",
    statusReady: "点击开始游戏",
    statusLoading: "对局进行中...",
    statusError: "出错了",
    day: "第",
    alive: "存活",
    dead: "出局",
    history: "历史对局",
    noHistory: "暂无对局记录",
    nightPhase: "夜晚行动",
    speech: "发言",
    vote: "投票",
    died: "{player} 因 {reason} 出局",
    modeAi: "纯 AI 对战",
    modeHuman: "AI + 人类",
    actionTitle: "等待你的行动",
    actionSubmit: "提交行动",
    target: "目标",
    statusHuman: "等待真人输入",
    room: "房间",
    seat: "座位",
    players: "人数",
    actionPlaceholder: "输入你的发言...",
    winnerVillage: "好人阵营",
    winnerWolf: "狼人阵营",
  },
  en: {
    run: "Start Game",
    private: "Moderator",
    public: "Public",
    winner: "Winner",
    statusReady: "Click to start",
    statusLoading: "Game in progress...",
    statusError: "Error",
    day: "Day",
    alive: "Alive",
    dead: "Dead",
    history: "History",
    noHistory: "No games yet",
    nightPhase: "Night Actions",
    speech: "Speeches",
    vote: "Votes",
    died: "{player} died by {reason}",
    modeAi: "AI vs AI",
    modeHuman: "AI + Human",
    actionTitle: "Your turn",
    actionSubmit: "Submit action",
    target: "Target",
    statusHuman: "Waiting for human input",
    room: "Room",
    seat: "Seat",
    players: "Players",
    actionPlaceholder: "Type your speech...",
    winnerVillage: "Village",
    winnerWolf: "Wolves",
  },
};

const state = {
  lang: new URL(window.location).searchParams.get("lang") === "en" ? "en" : "zh",
  showPrivate: false,
  busy: false,
  roomId: null,
  gameId: null,
  lastSnapshot: null,
  historyGames: [],
  mode: "ai",
  agentType: "llm",
  playerCount: 7,
  humanSeat: 1,
  pendingInput: null,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  run: $("#run"),
  private: $("#private"),
  langZh: $("#lang-zh"),
  langEn: $("#lang-en"),
  mode: $("#mode-select"),
  agentType: $("#agent-type"),
  playerCount: $("#player-count"),
  humanSeat: $("#human-seat"),
  statusDay: $("#status-day"),
  statusPhase: $("#status-phase"),
  statusRoom: $("#status-room"),
  playersLeft: $("#players-left"),
  playersRight: $("#players-right"),
  flow: $("#flow"),
  winnerBanner: $("#winner-banner"),
  winnerText: $("#winner-text"),
  historyPanel: $("#history-panel"),
  actionPanel: $("#action-panel"),
  actionTitle: $("#action-title"),
  actionPrompt: $("#action-prompt"),
  actionSpeech: $("#action-speech"),
  actionTarget: $("#action-target"),
  actionSave: $("#action-save"),
  actionSubmit: $("#action-submit"),
  actionVoice: $("#action-voice"),
  voiceHint: $("#voice-hint"),
};

// --- Voice input (Web Speech API) ---
const voice = {
  recognition: null,
  recording: false,
  startTextLen: 0,
};

function initVoice() {
  if (!els.actionVoice) return;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    els.actionVoice.classList.add("unsupported");
    els.actionVoice.title = "当前浏览器不支持语音输入，请使用 Chrome/Edge 或继续用键盘输入";
    return;
  }
  const rec = new SpeechRecognition();
  rec.lang = state.lang === "en" ? "en-US" : "zh-CN";
  rec.interimResults = true;
  rec.continuous = true;
  rec.onresult = (event) => {
    let finalText = "";
    let interimText = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (result.isFinal) finalText += result[0].transcript;
      else interimText += result[0].transcript;
    }
    const base = (els.actionSpeech.value || "").slice(0, voice.startTextLen);
    els.actionSpeech.value = base + finalText + interimText;
  };
  rec.onend = () => {
    voice.recording = false;
    els.actionVoice.classList.remove("recording");
    els.voiceHint && els.voiceHint.classList.add("hidden");
  };
  rec.onerror = (event) => {
    console.warn("voice recognition error", event.error);
    voice.recording = false;
    els.actionVoice.classList.remove("recording");
    els.voiceHint && els.voiceHint.classList.add("hidden");
  };
  voice.recognition = rec;
  els.actionVoice.addEventListener("click", toggleVoice);
}

function toggleVoice() {
  if (!voice.recognition) return;
  if (voice.recording) {
    voice.recognition.stop();
    return;
  }
  voice.recognition.lang = state.lang === "en" ? "en-US" : "zh-CN";
  voice.startTextLen = (els.actionSpeech.value || "").length;
  if (voice.startTextLen > 0 && !els.actionSpeech.value.endsWith(" ")) {
    els.actionSpeech.value += " ";
    voice.startTextLen += 1;
  }
  try {
    voice.recognition.start();
    voice.recording = true;
    els.actionVoice.classList.add("recording");
    els.voiceHint && els.voiceHint.classList.remove("hidden");
    els.actionSpeech.focus();
  } catch (err) {
    console.warn("voice start failed", err);
  }
}

function t(key) {
  return (I18N[state.lang] || I18N.en)[key] || key;
}

function fmt(template, values) {
  let output = template;
  Object.keys(values).forEach((key) => {
    output = output.replace(`{${key}}`, values[key]);
  });
  return output;
}

function esc(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

applyLang();
bindEvents();
initVoice();
bootstrap();

function bindEvents() {
  els.langZh.addEventListener("click", () => switchLang("zh"));
  els.langEn.addEventListener("click", () => switchLang("en"));
  els.private.addEventListener("click", async () => {
    state.showPrivate = !state.showPrivate;
    applyLang();
    if (state.gameId && state.lastSnapshot && state.lastSnapshot.winner) {
      try {
        const response = await fetch(`/api/games/${state.gameId}?show_private=${state.showPrivate ? "true" : "false"}`);
        if (response.ok) {
          const snapshot = await response.json();
          render(snapshot);
          return;
        }
      } catch {
      }
    }
    if (state.lastSnapshot) render(state.lastSnapshot);
  });
  els.mode.addEventListener("change", async () => {
    state.mode = els.mode.value;
    await recreateRoom();
    applyLang();
  });
  els.agentType.addEventListener("change", async () => {
    state.agentType = els.agentType.value;
    await recreateRoom();
  });
  els.playerCount.addEventListener("change", async () => {
    state.playerCount = Number(els.playerCount.value);
    if (state.humanSeat > state.playerCount) {
      state.humanSeat = state.playerCount;
    }
    renderHumanSeatOptions();
    await recreateRoom();
  });
  els.humanSeat.addEventListener("change", async () => {
    state.humanSeat = Number(els.humanSeat.value);
    if (state.mode === "human") {
      await recreateRoom();
    }
  });
  els.run.addEventListener("click", () => runGame());
  els.actionSubmit.addEventListener("click", () => submitHumanAction());
}

function switchLang(lang) {
  state.lang = lang;
  applyLang();
  if (state.lastSnapshot) render(state.lastSnapshot);
}

function applyLang() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  els.langZh.classList.toggle("active", state.lang === "zh");
  els.langEn.classList.toggle("active", state.lang === "en");
  els.private.textContent = state.showPrivate ? t("public") : t("private");
  els.run.textContent = t("run");
  els.actionTitle.textContent = t("actionTitle");
  els.actionSubmit.textContent = t("actionSubmit");
  els.actionSpeech.placeholder = t("actionPlaceholder");
  els.mode.querySelector('option[value="ai"]').textContent = t("modeAi");
  els.mode.querySelector('option[value="human"]').textContent = t("modeHuman");
  updateStatusRoom();
  renderHistoryPanel();
}

async function bootstrap() {
  els.mode.value = state.mode;
  els.agentType.value = state.agentType;
  els.playerCount.value = String(state.playerCount);
  renderHumanSeatOptions();
  els.humanSeat.value = String(state.humanSeat);
  els.statusPhase.textContent = t("statusReady");
  await loadHistory();
  await ensureRoom();
}

async function recreateRoom() {
  state.roomId = null;
  state.lastSnapshot = null;
  state.pendingInput = null;
  hideActionPanel();
  await ensureRoom();
}

async function ensureRoom() {
  if (state.roomId) {
    updateStatusRoom();
    return;
  }
  const seed = Math.floor(Math.random() * 1000);
  const qs = new URLSearchParams({
    name: "Demo",
    seed: String(seed),
    player_count: String(state.playerCount),
    agent_type: "llm",
    rule_pack_id: "wolfcha-default",
  });
  if (state.mode === "human") {
    qs.set("human_seat", String(state.humanSeat));
  }
  qs.set("agent_type", state.agentType);
  const response = await fetch(`/api/rooms?${qs.toString()}`, { method: "POST" });
  if (!response.ok) {
    throw new Error("Failed to create room");
  }
  const room = await response.json();
  state.roomId = room.id;
  updateStatusRoom();
}

function updateStatusRoom() {
  const roomText = state.roomId ? `${t("room")} ${state.roomId.slice(0, 8)}` : `${t("room")} -`;
  const countText = ` · ${t("players")} ${state.playerCount}`;
  const seatText = state.mode === "human" ? ` · ${t("seat")} ${state.humanSeat}` : "";
  els.statusRoom.textContent = roomText + countText + seatText;
}

function renderHumanSeatOptions() {
  els.humanSeat.innerHTML = Array.from({ length: state.playerCount }, (_, idx) => {
    const seat = idx + 1;
    return `<option value="${seat}">${t("seat")} ${seat}</option>`;
  }).join("");
  els.humanSeat.value = String(state.humanSeat);
}

async function loadHistory() {
  try {
    const response = await fetch("/api/history?limit=10");
    state.historyGames = response.ok ? await response.json() : [];
  } catch {
    state.historyGames = [];
  }
  renderHistoryPanel();
}

function renderHistoryPanel() {
  if (!els.historyPanel) return;
  if (!state.historyGames.length) {
    els.historyPanel.innerHTML = `<div class="history-empty">${t("noHistory")}</div>`;
    return;
  }
  els.historyPanel.innerHTML = state.historyGames.slice(0, 8).map((game) => {
    const winner = game.winner === "village" ? t("winnerVillage") : game.winner === "wolf" ? t("winnerWolf") : "?";
    return `<div class="history-item">
      <span class="hist-winner">${esc(winner)}</span>
      <span class="hist-day">${t("day")} ${esc(game.current_day || 0)}</span>
      <span class="hist-date">${esc((game.created_at || "").slice(0, 10))}</span>
    </div>`;
  }).join("");
}

async function runGame() {
  if (state.busy) return;
  state.busy = true;
  els.run.disabled = true;
  els.statusPhase.textContent = t("statusLoading");
  els.flow.innerHTML = "";
  els.winnerBanner.classList.add("hidden");
  hideActionPanel();
  try {
    await ensureRoom();
    const snapshot = state.mode === "human" ? await startHumanRoom() : await runAiRoom();
    render(snapshot);
    await loadHistory();
  } catch (error) {
    els.statusPhase.textContent = `${t("statusError")}: ${error.message || error}`;
  } finally {
    state.busy = false;
    els.run.disabled = false;
  }
}

async function startHumanRoom() {
  const response = await fetch(`/api/rooms/${state.roomId}/start`, { method: "POST" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to start room" }));
    throw new Error(error.detail || "Failed to start room");
  }
  const snapshot = await response.json();
  render(snapshot);
  return snapshot;
}

function runAiRoom() {
  return new Promise((resolve, reject) => {
    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/rooms/${state.roomId}`;
    const socket = new WebSocket(wsUrl);
    let finalState = null;
    socket.onopen = () => {
      socket.send(JSON.stringify({
        action: "start",
        seed: Math.floor(Math.random() * 1000),
        show_private: state.showPrivate,
        agent_type: state.agentType,
      }));
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "error") {
        socket.close();
        reject(new Error(message.message));
        return;
      }
      if (message.type === "snapshot" && message.state) {
        finalState = message.state;
        renderLive(message.state);
      }
      if (message.type === "complete" && message.state) {
        finalState = message.state;
        socket.close();
        resolve(finalState);
      }
    };
    socket.onerror = () => reject(new Error("WebSocket error"));
    socket.onclose = () => {
      if (!finalState) reject(new Error("Connection closed"));
    };
  });
}

async function submitHumanAction() {
  if (!state.pendingInput) return;
  const payload = {
    target_id: els.actionTarget.value || null,
    speech: els.actionSpeech.value.trim() || null,
    save: els.actionSave.checked,
    reasoning: "Human action from UI",
  };
  const response = await fetch(`/api/rooms/${state.roomId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to submit action" }));
    els.statusPhase.textContent = `${t("statusError")}: ${error.detail || "Failed to submit action"}`;
    return;
  }
  const snapshot = await response.json();
  hideActionPanel();
  render(snapshot);
  if (snapshot.winner) {
    await loadHistory();
  }
}

function renderLive(snapshot) {
  state.lastSnapshot = snapshot;
  render(snapshot);
}

function render(snapshot) {
  state.lastSnapshot = snapshot;
  state.gameId = snapshot.id || state.gameId;
  state.pendingInput = snapshot.pending_input || null;
  const day = snapshot.day || 0;
  els.statusDay.textContent = day > 0 ? `${t("day")} ${day}` : "-";
  els.statusPhase.textContent = snapshot.pending_input ? t("statusHuman") : (snapshot.phase || t("statusReady"));
  renderPlayers(snapshot.players || [], snapshot.current_speaker_id);
  renderFlow(snapshot);
  renderWinner(snapshot);
  renderPendingInput(snapshot.pending_input);
}

function renderWinner(snapshot) {
  if (!snapshot.winner) {
    els.winnerBanner.classList.add("hidden");
    return;
  }
  els.winnerBanner.classList.remove("hidden");
  els.winnerText.textContent = snapshot.winner === "village" ? t("winnerVillage") : t("winnerWolf");
}

function renderPlayers(players, currentSpeakerId) {
  const midpoint = Math.ceil(players.length / 2);
  els.playersLeft.innerHTML = players.slice(0, midpoint).map((player) => playerCard(player, currentSpeakerId)).join("");
  els.playersRight.innerHTML = players.slice(midpoint).map((player) => playerCard(player, currentSpeakerId)).join("");
}

function playerCard(player, currentSpeakerId) {
  const status = player.alive ? t("alive") : t("dead");
  let roleText = status;
  let avatarColor = "var(--ink)";
  const personaText = player.persona && player.persona.style_label ? ` · ${player.persona.style_label}` : "";
  const sheriff = state.lastSnapshot && state.lastSnapshot.badge && state.lastSnapshot.badge.holder_id === player.id ? " 👑" : "";
  if (state.showPrivate && player.role) {
    roleText = `${player.role}${personaText} · ${status}`;
    avatarColor = player.alignment === "wolf" ? "var(--wolf)" : "var(--village)";
  } else if (personaText) {
    roleText = `${status}${personaText}`;
  }
  return `<div class="player-card ${player.alive ? "" : "dead"} ${player.id === currentSpeakerId ? "speaking" : ""}">
    <div class="player-avatar" style="background:${avatarColor}">${esc((player.name || "?")[0])}</div>
    <div class="player-info">
      <div class="player-name">${esc(player.name || "?")}${sheriff}${player.is_ai ? "" : " · HUMAN"}</div>
      <div class="player-role">${esc(roleText)}</div>
    </div>
  </div>`;
}

function renderPendingInput(pending) {
  if (!pending) {
    hideActionPanel();
    return;
  }
  els.actionPanel.classList.remove("hidden");
  els.actionTitle.textContent = `${pending.player_name} · ${pending.phase}`;
  els.actionPrompt.textContent = pending.prompt || t("actionTitle");
  els.actionSpeech.value = "";
  els.actionSave.checked = false;
  const showSpeech = pending.action_type === "speech";
  const showTarget = pending.action_type !== "speech";
  const showSave = pending.request === "WITCH";
  els.actionSpeech.style.display = showSpeech ? "block" : "none";
  els.actionTarget.parentElement.style.display = showTarget ? "block" : "none";
  els.actionSave.parentElement.style.display = showSave ? "flex" : "none";
  els.actionTarget.innerHTML = `<option value="">-</option>` + (pending.options || []).map((option) => {
    return `<option value="${esc(option.id)}">${esc(option.seat)} · ${esc(option.name)}</option>`;
  }).join("");
}

function hideActionPanel() {
  els.actionPanel.classList.add("hidden");
  state.pendingInput = null;
}

function renderFlow(snapshot) {
  const events = snapshot.events || [];
  if (!events.length) {
    els.flow.innerHTML = `<div class="flow-placeholder">${t("statusReady")}</div>`;
    return;
  }
  const days = {};
  for (const event of events) {
    const day = event.day || 0;
    if (!days[day]) {
      days[day] = { night: [], speeches: [], votes: [], deaths: [], system: [] };
    }
    const type = event.type;
    if (type === "CHAT_MESSAGE") days[day].speeches.push(event);
    if (type === "VOTE_CAST") days[day].votes.push(event);
    if (type === "PLAYER_DIED") days[day].deaths.push(event);
    if (type === "SYSTEM_MESSAGE" || type === "WHITE_WOLF_KING_BOOM") days[day].system.push(event);
    if (type === "NIGHT_ACTION" || type === "PRIVATE_INFO") days[day].night.push(event);
  }
  let html = "";
  Object.keys(days).sort((a, b) => Number(a) - Number(b)).forEach((dayKey) => {
    if (Number(dayKey) === 0) return;
    const block = days[dayKey];
    html += `<div class="day-block"><div class="day-header"><span class="day-num">${t("day")} ${dayKey}</span>`;
    if (block.deaths.length) {
      html += `<span class="day-deaths">${block.deaths.map((event) => fmt(t("died"), { player: event.payload.player_name, reason: event.payload.reason })).join(" · ")}</span>`;
    }
    html += `</div>`;
    if (state.showPrivate && block.night.length) {
      html += `<div class="phase-block"><div class="phase-label">${t("nightPhase")}</div>`;
      block.night.forEach((event) => {
        html += `<div class="night-entry">${esc(event.payload.actor_name || "system")} → ${esc(event.payload.target_name || event.payload.target_id || "")}</div>`;
      });
      html += `</div>`;
    }
    if (block.speeches.length) {
      html += `<div class="phase-block"><div class="phase-label">${t("speech")}</div>`;
      block.speeches.forEach((event) => {
        const tag = event.payload.last_words ? "【LAST】" : event.payload.badge_campaign ? "【BADGE】" : "";
        html += `<div class="speech-entry ${event.payload.last_words ? "last-words" : ""}">
          <div class="speech-avatar">${esc((event.payload.actor_name || "?")[0])}</div>
          <div class="speech-body">
            <div class="speech-speaker">${esc(event.payload.actor_name || "?")} ${tag}</div>
            <div class="speech-text">${esc(event.payload.speech || "")}</div>
          </div>
        </div>`;
      });
      html += `</div>`;
    }
    if (block.system.length) {
      html += `<div class="phase-block"><div class="phase-label">System</div>`;
      block.system.forEach((event) => {
        const text = event.type === "WHITE_WOLF_KING_BOOM"
          ? `${event.payload.boom_player_name || ""} → ${event.payload.target_name || ""}`
          : (event.payload.message || "");
        html += `<div class="night-entry">${esc(text)}</div>`;
      });
      html += `</div>`;
    }
    if (block.votes.length) {
      html += `<div class="phase-block"><div class="phase-label">${t("vote")}</div>`;
      block.votes.forEach((event) => {
        html += `<div class="vote-entry"><span class="vote-voter">${esc(event.payload.voter_name || "")}</span><span class="vote-arrow">→</span><span class="vote-target">${esc(event.payload.target_name || "")}</span></div>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
  });
  els.flow.innerHTML = html || `<div class="flow-placeholder">${t("statusReady")}</div>`;
}
