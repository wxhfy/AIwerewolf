const I18N = {
  zh: { run: "开始游戏", private: "主持视角", public: "公开视角", winner: "胜者",
    statusReady: "点击开始游戏", statusLoading: "对局进行中...",
    statusError: "出错了", day: "天", night: "夜",
    alive: "存活", dead: "出局", history: "历史对局", noHistory: "暂无对局记录",
    nightPhase: "夜晚行动", speech: "发言", vote: "投票",
    died: "{player} 因 {reason} 出局", wins: "{winner} 获胜",
  },
  en: { run: "Start Game", private: "Moderator", public: "Public", winner: "Winner",
    statusReady: "Click to start", statusLoading: "Game in progress...",
    statusError: "Error", day: "Day", night: "Night",
    alive: "Alive", dead: "Dead", history: "History", noHistory: "No games yet",
    nightPhase: "Night Actions", speech: "Speeches", vote: "Votes",
    died: "{player} died by {reason}", wins: "{winner} wins",
  }
};

const state = {
  lang: (new URL(window.location).searchParams.get("lang") === "en" ? "en" : "zh"),
  showPrivate: false, busy: false, roomId: null, gameId: null,
  lastSnapshot: null, historyGames: [],
};

function t(key) { return (I18N[state.lang] || I18N.en)[key] || key; }
function fmt(tpl, vals) { let s = tpl; for (let k in vals) s = s.replace(`{${k}}`, vals[k]); return s; }

const $ = (s) => document.querySelector(s);
const els = {
  run: $("#run"), private: $("#private"), langZh: $("#lang-zh"), langEn: $("#lang-en"),
  statusDay: $("#status-day"), statusPhase: $("#status-phase"),
  playersLeft: $("#players-left"), playersRight: $("#players-right"),
  flow: $("#flow"), winnerBanner: $("#winner-banner"), winnerText: $("#winner-text"),
  historyPanel: $("#history-panel"),
};

applyLang();
bootstrap();

function applyLang() {
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.title = "AI Werewolf";
  els.langZh.classList.toggle("active", state.lang === "zh");
  els.langEn.classList.toggle("active", state.lang === "en");
  els.private.textContent = state.showPrivate ? t("public") : t("private");
}

els.langZh.addEventListener("click", () => { state.lang = "zh"; applyLang(); if(state.lastSnapshot) render(state.lastSnapshot); });
els.langEn.addEventListener("click", () => { state.lang = "en"; applyLang(); if(state.lastSnapshot) render(state.lastSnapshot); });
els.private.addEventListener("click", () => { state.showPrivate = !state.showPrivate; applyLang(); if(state.lastSnapshot) render(state.lastSnapshot); });
els.run.addEventListener("click", () => runGame());

async function bootstrap() {
  els.statusPhase.textContent = t("statusReady");
  await loadHistory();
  await ensureRoom();
}

async function ensureRoom() {
  const urlRoom = new URL(window.location).searchParams.get("room");
  if (urlRoom) {
    try {
      const r = await fetch(`/api/rooms/${urlRoom}`);
      if (r.ok) { state.roomId = (await r.json()).id; return; }
    } catch(e) {}
    const u = new URL(window.location); u.searchParams.delete("room");
    window.history.replaceState({}, "", u);
  }
  if (state.roomId) return;
  const r = await fetch(`/api/rooms?name=Demo&seed=${Math.floor(Math.random()*100)}&player_count=7&agent_type=llm`, {method:"POST"});
  if (!r.ok) throw new Error("Failed to create room");
  const room = await r.json();
  state.roomId = room.id;
  const u = new URL(window.location); u.searchParams.set("room", room.id);
  window.history.replaceState({}, "", u);
}

async function loadHistory() {
  try {
    const r = await fetch("/api/history?limit=10");
    if (r.ok) state.historyGames = await r.json();
  } catch(e) { state.historyGames = []; }
  renderHistoryPanel();
}

function renderHistoryPanel() {
  const panel = els.historyPanel;
  if (!panel) return;
  if (!state.historyGames.length) {
    panel.innerHTML = `<div class="history-empty">${t("noHistory")}</div>`;
    return;
  }
  panel.innerHTML = state.historyGames.slice(0, 8).map(g => {
    const w = g.winner === "village" ? "好人" : g.winner === "wolf" ? "狼人" : "?";
    const date = (g.created_at || "").slice(0, 10);
    return `<div class="history-item" data-id="${g.id}" title="点击查看对局详情">
      <span class="hist-winner">${w}胜</span>
      <span class="hist-day">第${g.current_day}天</span>
      <span class="hist-date">${date}</span>
    </div>`;
  }).join("");
  // Click handler: load historical game
  panel.querySelectorAll(".history-item").forEach(el => {
    el.addEventListener("click", async () => {
      const gameId = el.dataset.id;
      if (!gameId) return;
      try {
        const r = await fetch(`/api/history/${gameId}`);
        if (!r.ok) return;
        const summary = await r.json();
        loadHistoryGame(summary);
      } catch(e) {}
    });
  });
}

async function runGame() {
  if (state.busy) return;
  state.busy = true;
  els.run.disabled = true;
  els.statusPhase.textContent = t("statusLoading");
  els.flow.innerHTML = "";
  els.winnerBanner.classList.add("hidden");

  try {
    await ensureRoom();
    const game = await runGameWS();
    render(game);
    await loadHistory();
  } catch(e) {
    els.statusPhase.textContent = t("statusError") + ": " + (e.message || e);
  } finally {
    state.busy = false;
    els.run.disabled = false;
  }
}

function runGameWS() {
  return new Promise((resolve, reject) => {
    if (!state.roomId) return reject(new Error("No room"));
    const wsUrl = `${location.protocol==="https:"?"wss":"ws"}://${location.host}/ws/rooms/${state.roomId}`;
    const ws = new WebSocket(wsUrl);
    let final = null;

    ws.onopen = () => ws.send(JSON.stringify({
      action: "start", seed: Math.floor(Math.random()*100),
      show_private: state.showPrivate, agent_type: "llm"
    }));

    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === "error") { ws.close(); return reject(new Error(d.message)); }
      if (d.type === "snapshot" && d.state) {
        final = d.state;
        renderLive(d.state);
      }
      if (d.type === "complete") {
        final = d.state || final;
        ws.close();
        if (final) { render(final); resolve(final); }
        else reject(new Error("No game state"));
      }
    };
    ws.onerror = () => reject(new Error("WebSocket error"));
    ws.onclose = () => { if (!final) reject(new Error("Connection closed")); };
  });
}

function renderLive(snapshot) {
  state.lastSnapshot = snapshot;
  const day = snapshot.day || 0;
  const phase = (snapshot.phase || "").replace(/_/g, " ");
  els.statusDay.textContent = day > 0 ? `Day ${day}` : "准备";
  els.statusPhase.textContent = phase;
  if (snapshot.players) renderPlayers(snapshot.players);
  if (snapshot.events && snapshot.events.length) renderFlow(snapshot);
}

function render(snapshot) {
  state.lastSnapshot = snapshot;
  const day = snapshot.day || 0;
  els.statusDay.textContent = `Day ${day}`;
  els.statusPhase.textContent = snapshot.phase || "";
  renderPlayers(snapshot.players || []);
  renderFlow(snapshot);
  if (snapshot.winner) {
    els.winnerBanner.classList.remove("hidden");
    els.winnerText.textContent = snapshot.winner === "village" ? "好人阵营" : "狼人阵营";
  }
}

function renderPlayers(players) {
  const half = Math.ceil(players.length / 2);
  els.playersLeft.innerHTML = players.slice(0, half).map(p => playerCard(p)).join("");
  els.playersRight.innerHTML = players.slice(half).map(p => playerCard(p)).join("");
}

function playerCard(p) {
  const status = p.alive ? t("alive") : t("dead");
  // Only show role/alignment in moderator view
  let roleText = status;
  let bgColor = "var(--ink)";
  if (state.showPrivate && p.role) {
    roleText = p.role + " · " + status;
    bgColor = p.alignment === "wolf" ? "var(--wolf)" : "var(--village)";
  }
  const initial = (p.name || "?")[0];
  return `<div class="player-card ${p.alive?'':'dead'}">
    <div class="player-avatar" style="background:${bgColor}">${initial}</div>
    <div class="player-info">
      <div class="player-name">${esc(p.name||'?')}</div>
      <div class="player-role">${roleText}</div>
    </div>
  </div>`;
}

function renderFlow(snapshot) {
  const events = snapshot.events || [];
  if (!events.length) { els.flow.innerHTML = `<div class="flow-placeholder">${t("statusReady")}</div>`; return; }

  const days = {};
  for (const e of events) {
    const d = e.day || 0;
    if (!days[d]) days[d] = { night: [], speeches: [], votes: [], deaths: [] };
    const type = e.type;
    const p = e.payload || {};
    if (type === "NIGHT_ACTION" || type === "PRIVATE_INFO") {
      days[d].night.push(e);
    } else if (type === "CHAT_MESSAGE") {
      days[d].speeches.push(e);
    } else if (type === "VOTE_CAST") {
      days[d].votes.push(e);
    } else if (type === "PLAYER_DIED") {
      days[d].deaths.push(e);
    }
  }

  let html = "";
  for (const [dayNum, d] of Object.entries(days)) {
    if (dayNum == 0) continue;
    html += `<div class="day-block">
      <div class="day-header">
        <span class="day-num">${t("day")} ${dayNum}</span>`;
    if (d.deaths.length) {
      html += `<span class="day-deaths">${d.deaths.map(e=>fmt(t("died"),{player:e.payload.player_name,reason:e.payload.reason})).join(" · ")}</span>`;
    }
    html += `</div>`;

    if (state.showPrivate && d.night.length) {
      html += `<div class="phase-block">
        <div class="phase-label">${t("nightPhase")}</div>`;
      for (const e of d.night) {
        const p = e.payload;
        html += `<div class="night-entry"><span class="night-actor">${esc(p.actor_name||'')}</span> → <span class="night-target">${esc(p.target_name||p.target_id||'?')}</span></div>`;
      }
      html += `</div>`;
    }

    if (d.speeches.length) {
      html += `<div class="phase-block">
        <div class="phase-label">${t("speech")}</div>`;
      for (const e of d.speeches) {
        const p = e.payload;
        const isLast = p.last_words ? " 【遗言】" : "";
        html += `<div class="speech-entry ${p.last_words?'last-words':''}">
          <div class="speech-avatar">${esc((p.actor_name||'?')[0])}</div>
          <div class="speech-body">
            <div class="speech-speaker">${esc(p.actor_name||'?')} 说：${isLast}</div>
            <div class="speech-text">"${esc(p.speech||'')}"</div>
          </div>
        </div>`;
      }
      html += `</div>`;
    }

    if (d.votes.length) {
      html += `<div class="phase-block">
        <div class="phase-label">${t("vote")}</div>`;
      for (const e of d.votes) {
        const p = e.payload;
        html += `<div class="vote-entry"><span class="vote-voter">${esc(p.voter_name||'')}</span> <span class="vote-arrow">→</span> <span class="vote-target">${esc(p.target_name||'')}</span></div>`;
      }
      html += `</div>`;
    }

    html += `</div>`;
  }
  els.flow.innerHTML = html || `<div class="flow-placeholder">${t("statusReady")}</div>`;
}

function loadHistoryGame(summary) {
  // Clear current live state
  state.lastSnapshot = summary;
  state.gameId = summary.id;
  els.statusDay.textContent = `Day ${summary.day || 0}`;
  els.statusPhase.textContent = summary.winner === "village" ? "好人阵营获胜" : summary.winner === "wolf" ? "狼人阵营获胜" : "已结束";
  // Show players
  renderPlayers(summary.players || []);
  // Show flow from speeches/votes/deaths
  renderHistoryFlow(summary);
  // Show winner
  if (summary.winner) {
    els.winnerBanner.classList.remove("hidden");
    els.winnerText.textContent = summary.winner === "village" ? "好人阵营" : "狼人阵营";
  }
}

function renderHistoryFlow(summary) {
  const days = {};
  for (const s of (summary.speeches || [])) {
    const d = s.day || 1;
    if (!days[d]) days[d] = { speeches: [], votes: [], deaths: [] };
    days[d].speeches.push(s);
  }
  for (const v of (summary.votes || [])) {
    const d = v.day || 1;
    if (!days[d]) days[d] = { speeches: [], votes: [], deaths: [] };
    days[d].votes.push(v);
  }
  for (const dd of (summary.deaths || [])) {
    const d = dd.day || 1;
    if (!days[d]) days[d] = { speeches: [], votes: [], deaths: [] };
    days[d].deaths.push(dd);
  }

  let html = "";
  for (const [dayNum, d] of Object.entries(days)) {
    html += `<div class="day-block">
      <div class="day-header">
        <span class="day-num">${t("day")} ${dayNum}</span>`;
    if (d.deaths.length) {
      html += `<span class="day-deaths">${d.deaths.map(dd=>fmt(t("died"),{player:dd.player,reason:dd.reason})).join(" · ")}</span>`;
    }
    html += `</div>`;
    if (d.speeches.length) {
      html += `<div class="phase-block"><div class="phase-label">${t("speech")}</div>`;
      for (const s of d.speeches) {
        html += `<div class="speech-entry">
          <div class="speech-avatar">${esc((s.speaker||'?')[0])}</div>
          <div class="speech-body">
            <div class="speech-speaker">${esc(s.speaker||'?')} 说：</div>
            <div class="speech-text">"${esc(s.text||'')}"</div>
          </div>
        </div>`;
      }
      html += `</div>`;
    }
    if (d.votes.length) {
      html += `<div class="phase-block"><div class="phase-label">${t("vote")}</div>`;
      for (const v of d.votes) {
        html += `<div class="vote-entry"><span class="vote-voter">${esc(v.voter||'')}</span> <span class="vote-arrow">→</span> <span class="vote-target">${esc(v.target||'')}</span></div>`;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  els.flow.innerHTML = html || `<div class="flow-placeholder">无对局数据</div>`;
}

function esc(s) { if (!s) return ""; return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
