import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";

const root = process.cwd();
const outputDir = path.join(root, "docs/experiments/full_project_real_audit");

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close(() => (port ? resolve(port) : reject(new Error("Unable to allocate free port"))));
    });
  });
}

function terminateProcess(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }, 3000);
    child.once("close", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

async function terminateTree(child) {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
  await Promise.race([terminateProcess(child), wait(3000)]);
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch {
    // already stopped
  }
}

async function waitForServer(url, retries = 160) {
  for (let i = 0; i < retries; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // keep waiting
    }
    await wait(250);
  }
  throw new Error(`Server did not become ready: ${url}`);
}

async function jsonFetch(url, init) {
  const response = await fetch(url, init);
  const body = await response.json().catch(() => ({}));
  return { response, body };
}

async function createStartedHumanRoom(backendBase, { seed, humanSeat }) {
  const create = await jsonFetch(
    `${backendBase}/api/rooms?name=HumanProbe&seed=${seed}&player_count=7&agent_type=llm&human_seat=${humanSeat}`,
    { method: "POST" },
  );
  if (!create.response.ok) throw new Error(`create human room failed: ${create.response.status}`);
  const start = await jsonFetch(`${backendBase}/api/rooms/${create.body.id}/start`, { method: "POST" });
  if (!start.response.ok) throw new Error(`start human room failed: ${start.response.status}`);
  return { room: create.body, state: start.body };
}

function logEvent(logs, type, payload) {
  logs.push({ type, payload: String(payload).slice(0, 1000) });
}

async function dismissRoleReveal(page) {
  await page.getByTestId("role-reveal-overlay").waitFor({ state: "visible", timeout: 20000 }).catch(() => {});
  await page.getByTestId("role-reveal-overlay").waitFor({ state: "detached", timeout: 6000 }).catch(() => {});
}

async function assertNoPageCrash(page) {
  const text = await page.locator("body").innerText({ timeout: 10000 });
  if (/Unhandled Runtime Error|Application error|TypeError|ReferenceError/.test(text)) {
    throw new Error(`Page crash text found: ${text.slice(0, 500)}`);
  }
}

await fs.mkdir(outputDir, { recursive: true });

const backendPort = await getFreePort();
const frontendPort = await getFreePort();
const pythonBin = process.env.PYTHON || "python";

const backendLogs = [];
const frontendLogs = [];
const backend = spawn(
  pythonBin,
  ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
  {
    cwd: root,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      PYTHONPATH: root,
      _TEST_ALLOW_FAKE_LLM: "true",
      LLM_PROVIDER: "fake",
      AIWEREWOLF_DEFAULT_AGENT_TYPE: "llm",
      MODEL_POOL: "fake:fake-llm",
      DOUBAO_MODEL_POOL: "fake:fake-llm",
    },
  },
);
backend.stdout.on("data", (chunk) => logEvent(backendLogs, "stdout", chunk));
backend.stderr.on("data", (chunk) => logEvent(backendLogs, "stderr", chunk));

const frontend = spawn(
  path.join(root, "frontend", "node_modules", ".bin", "next"),
  ["dev", "-p", String(frontendPort)],
  {
    cwd: path.join(root, "frontend"),
    detached: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
      NEXT_PUBLIC_BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
      NEXT_DIST_DIR: ".next-human-probe",
    },
  },
);
frontend.stdout.on("data", (chunk) => logEvent(frontendLogs, "stdout", chunk));
frontend.stderr.on("data", (chunk) => logEvent(frontendLogs, "stderr", chunk));

let browser;
const evidence = {
  generatedAt: new Date().toISOString(),
  backendPort,
  frontendPort,
  requests: [],
  console: [],
  pageErrors: [],
  lobby: {},
  humanTarget: {},
  humanWolfVote: {},
  badStates: {},
  pauseControl: {},
  assertions: {},
  backendLogs,
  frontendLogs,
};

try {
  const backendBase = `http://127.0.0.1:${backendPort}`;
  const frontendBase = `http://127.0.0.1:${frontendPort}`;
  await waitForServer(`${backendBase}/api/health`);
  await waitForServer(`${frontendBase}/`);

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("console", (msg) => evidence.console.push({ type: msg.type(), text: msg.text().slice(0, 1000) }));
  page.on("pageerror", (err) => evidence.pageErrors.push(String(err).slice(0, 1000)));
  page.on("request", (request) => {
    const url = request.url();
    if (/\/api\/rooms|\/ws\/rooms/.test(url)) {
      evidence.requests.push({ method: request.method(), url });
    }
  });

  await page.goto(`${frontendBase}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("mode-human-button").click();
  await page.getByRole("button", { name: "开始真人参与对局" }).waitFor({ state: "visible", timeout: 10000 });
  await page.getByTestId("human-seat-3-button").click();
  await page.getByRole("button", { name: "开始真人参与对局" }).click();
  await page.getByText("准备开始").waitFor({ timeout: 30000 });
  const modalText = await page.locator('[role="dialog"]').innerText();
  if (!modalText.includes("座位 3") || !modalText.includes("你")) {
    throw new Error(`Human lobby modal missing selected seat: ${modalText}`);
  }
  await page.getByRole("button", { name: "确认开始" }).click();
  await page.waitForURL(/\/room\/.+\/play\?mode=human.*human_seat=3/, { timeout: 30000 });
  evidence.lobby = { modalText, urlAfterConfirm: page.url() };
  await assertNoPageCrash(page);

  const badRoomPage = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await badRoomPage.goto(`${frontendBase}/room/not-a-real-room/play?mode=human&human_seat=1`, { waitUntil: "domcontentloaded" });
  await badRoomPage.getByText("重试").waitFor({ timeout: 30000 });
  evidence.badStates.invalidRoomText = (await badRoomPage.locator("body").innerText()).slice(0, 1000);
  await badRoomPage.close();

  const noActiveRoom = await jsonFetch(
    `${backendBase}/api/rooms?name=NoActiveHuman&seed=1&player_count=7&agent_type=llm&human_seat=1`,
    { method: "POST" },
  );
  const noActiveAction = await fetch(`${backendBase}/api/rooms/${noActiveRoom.body.id}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_id: null }),
  });
  evidence.badStates.noActiveActionStatus = noActiveAction.status;

  const witch = await createStartedHumanRoom(backendBase, { seed: 1, humanSeat: 1 });
  evidence.humanTarget.pendingBefore = witch.state.pending_input;
  if (witch.state.pending_input?.request !== "WITCH") {
    throw new Error(`Expected WITCH pending, got ${witch.state.pending_input?.request}`);
  }
  await page.goto(`${frontendBase}/room/${witch.room.id}/play?mode=human&human_seat=1`, { waitUntil: "domcontentloaded" });
  await dismissRoleReveal(page);
  await page.getByTestId("human-status-bar").waitFor({ state: "visible", timeout: 30000 });
  await page.getByTestId("human-action-bar").waitFor({ state: "visible", timeout: 30000 });
  const targetSubmit = page.getByTestId("human-submit-button");
  const targetSubmitDisabledBefore = await targetSubmit.isDisabled();
  const targetId = witch.state.pending_input.options[0].id;
  await page.locator(`[data-testid="player-card"][data-player-id="${targetId}"][data-selectable="true"]:visible`).first().click();
  const selectedText = await page.getByTestId("human-action-bar").innerText();
  const targetSubmitDisabledAfter = await targetSubmit.isDisabled();
  await targetSubmit.click();
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return text.includes("已提交，等待阶段推进") || !document.querySelector('[data-testid="human-action-bar"]');
  }, { timeout: 30000 });
  await page.screenshot({ path: path.join(outputDir, "human_ui_target_state.png"), fullPage: true });
  const witchSnapshot = await (await fetch(`${backendBase}/api/rooms/${witch.room.id}/snapshot`)).json();
  evidence.humanTarget = {
    ...evidence.humanTarget,
    targetSubmitDisabledBefore,
    targetSubmitDisabledAfter,
    selectedText,
    snapshotAfter: {
      phase: witchSnapshot.phase,
      pending_input: witchSnapshot.pending_input,
      event_count: witchSnapshot.event_count,
    },
  };

  const wolf = await createStartedHumanRoom(backendBase, { seed: 1, humanSeat: 5 });
  evidence.humanWolfVote.pendingBefore = wolf.state.pending_input;
  if (wolf.state.pending_input?.request !== "WOLF_TEAM_VOTE") {
    throw new Error(`Expected WOLF_TEAM_VOTE pending, got ${wolf.state.pending_input?.request}`);
  }
  if (wolf.state.pending_input?.action_type !== "night_action") {
    throw new Error(`WOLF_TEAM_VOTE should be a target action, got ${wolf.state.pending_input?.action_type}`);
  }
  await page.goto(`${frontendBase}/room/${wolf.room.id}/play?mode=human&human_seat=5`, { waitUntil: "domcontentloaded" });
  await dismissRoleReveal(page);
  await page.getByTestId("human-action-bar").waitFor({ state: "visible", timeout: 30000 });
  if (await page.getByTestId("human-speech-input").isVisible().catch(() => false)) {
    throw new Error("WOLF_TEAM_VOTE rendered as speech input instead of target selection");
  }
  const wolfSubmit = page.getByTestId("human-submit-button");
  const wolfSubmitDisabledBefore = await wolfSubmit.isDisabled();
  const wolfTargetId = wolf.state.pending_input.options[0].id;
  await page.locator(`[data-testid="player-card"][data-player-id="${wolfTargetId}"][data-selectable="true"]:visible`).first().click();
  const wolfSubmitDisabledAfter = await wolfSubmit.isDisabled();
  await wolfSubmit.click();
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return text.includes("已提交，等待阶段推进") || !document.querySelector('[data-testid="human-action-bar"]');
  }, { timeout: 30000 });
  await page.screenshot({ path: path.join(outputDir, "human_ui_wolf_vote_state.png"), fullPage: true });
  const wolfSnapshot = await (await fetch(`${backendBase}/api/rooms/${wolf.room.id}/snapshot`)).json();
  evidence.humanWolfVote = {
    ...evidence.humanWolfVote,
    wolfSubmitDisabledBefore,
    wolfSubmitDisabledAfter,
    snapshotAfter: {
      phase: wolfSnapshot.phase,
      pending_input: wolfSnapshot.pending_input,
      event_count: wolfSnapshot.event_count,
    },
  };

  const moderatorPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  moderatorPage.on("console", (msg) => evidence.console.push({ type: msg.type(), text: `[moderator] ${msg.text().slice(0, 980)}` }));
  await moderatorPage.goto(`${frontendBase}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await moderatorPage.evaluate(() => {
    localStorage.setItem("gameSettings", JSON.stringify({
      viewMode: "moderator",
      language: "zh",
      seed: 23,
      modelProvider: "anthropic",
      modelName: "deepseek-v4-flash",
      apiKey: "",
      baseUrl: "https://api.deepseek.com/anthropic",
      apiFormat: "anthropic_messages",
      authEnvVar: "ANTHROPIC_AUTH_TOKEN",
    }));
  });
  await moderatorPage.reload({ waitUntil: "domcontentloaded" });
  const aiRoom = await jsonFetch(
    `${backendBase}/api/rooms?name=ModeratorPause&seed=23&player_count=7&agent_type=llm`,
    { method: "POST" },
  );
  if (!aiRoom.response.ok) throw new Error(`create AI room failed: ${aiRoom.response.status}`);
  await moderatorPage.goto(`${frontendBase}/room/${aiRoom.body.id}/play?mode=ai`, { waitUntil: "domcontentloaded" });
  await moderatorPage.getByTestId("global-pause-toggle").waitFor({ state: "visible", timeout: 30000 });
  const aiRoomId = aiRoom.body.id;
  const pauseButton = moderatorPage.getByTestId("global-pause-toggle");
  const labelBeforePause = (await pauseButton.innerText()).trim();
  await pauseButton.click();
  await moderatorPage.waitForFunction(() => document.querySelector('[data-testid="global-pause-toggle"]')?.textContent?.includes("继续"), { timeout: 10000 });
  const pausedStatus = await (await fetch(`${backendBase}/api/rooms/${aiRoomId}/control-status`)).json();
  const eventCountBeforeWait = await moderatorPage.locator('[data-testid="timeline-chat-bubble"]').count();
  await wait(1500);
  const eventCountAfterWait = await moderatorPage.locator('[data-testid="timeline-chat-bubble"]').count();
  await pauseButton.click();
  await moderatorPage.waitForFunction(() => document.querySelector('[data-testid="global-pause-toggle"]')?.textContent?.includes("暂停"), { timeout: 10000 });
  const resumedStatus = await (await fetch(`${backendBase}/api/rooms/${aiRoomId}/control-status`)).json();
  await moderatorPage.screenshot({ path: path.join(outputDir, "human_ui_pause_control.png"), fullPage: true });
  evidence.pauseControl = {
    aiRoomId,
    labelBeforePause,
    pausedStatus,
    resumedStatus,
    eventCountBeforeWait,
    eventCountAfterWait,
  };
  await moderatorPage.close();

  const publicRoom = await jsonFetch(
    `${backendBase}/api/rooms?name=PublicPauseHidden&seed=24&player_count=7&agent_type=llm`,
    { method: "POST" },
  );
  const publicPage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await publicPage.goto(`${frontendBase}/room/${publicRoom.body.id}/play?mode=ai`, { waitUntil: "domcontentloaded" });
  await wait(1200);
  evidence.pauseControl.publicPauseButtonCount = await publicPage.getByTestId("global-pause-toggle").count();
  await publicPage.close();

  evidence.assertions = {
    lobbyHumanFlow: /mode=human/.test(evidence.lobby.urlAfterConfirm || ""),
    invalidRoomShowsRetry: /重试/.test(evidence.badStates.invalidRoomText || ""),
    noActiveActionRejected: evidence.badStates.noActiveActionStatus === 409,
    witchPendingIsTargetState: evidence.humanTarget.pendingBefore?.request === "WITCH",
    targetSubmitDisabledUntilSelection: evidence.humanTarget.targetSubmitDisabledBefore === true && evidence.humanTarget.targetSubmitDisabledAfter === false,
    wolfVoteTargetAction: evidence.humanWolfVote.pendingBefore?.request === "WOLF_TEAM_VOTE" && evidence.humanWolfVote.pendingBefore?.action_type === "night_action",
    wolfVoteSubmitDisabledUntilSelection: evidence.humanWolfVote.wolfSubmitDisabledBefore === true && evidence.humanWolfVote.wolfSubmitDisabledAfter === false,
    moderatorPauseVisibleAndWorks: evidence.pauseControl.labelBeforePause === "暂停" && evidence.pauseControl.pausedStatus?.paused === true && evidence.pauseControl.resumedStatus?.paused === false,
    audiencePauseHidden: evidence.pauseControl.publicPauseButtonCount === 0,
    noConsoleErrors: evidence.console.filter((item) => item.type === "error").length === 0,
    noPageErrors: evidence.pageErrors.length === 0,
  };

  const failed = Object.entries(evidence.assertions).filter(([, value]) => value !== true);
  if (failed.length) {
    throw new Error(`Human UI assertions failed: ${failed.map(([key]) => key).join(", ")}`);
  }
} finally {
  if (browser) await browser.close();
  await fs.writeFile(path.join(outputDir, "human_ui_probe.json"), JSON.stringify(evidence, null, 2), "utf-8");
  await Promise.all([terminateTree(frontend), terminateTree(backend)]);
}

console.log(JSON.stringify({
  output: path.join(outputDir, "human_ui_probe.json"),
  assertions: evidence.assertions,
}, null, 2));
