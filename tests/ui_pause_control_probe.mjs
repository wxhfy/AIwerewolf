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

async function waitForServer(url, retries = 180) {
  for (let i = 0; i < retries; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Keep polling until the dev server is ready.
    }
    await wait(250);
  }
  throw new Error(`Server did not become ready: ${url}`);
}

async function terminateTree(child) {
  if (!child?.pid) return;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
  await wait(2000);
  try {
    process.kill(-child.pid, "SIGKILL");
  } catch {
    // Already stopped.
  }
}

function logEvent(logs, type, payload) {
  logs.push({ type, payload: String(payload).slice(0, 1000) });
}

async function createRoom(backendBase, name, seed) {
  const response = await fetch(
    `${backendBase}/api/rooms?name=${encodeURIComponent(name)}&seed=${seed}&player_count=7&agent_type=llm`,
    { method: "POST" },
  );
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Create room failed (${response.status}): ${JSON.stringify(body)}`);
  return body;
}

async function setViewMode(page, frontendBase, viewMode, seed) {
  await page.goto(`${frontendBase}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.evaluate(
    ({ nextViewMode, nextSeed }) => {
      localStorage.setItem("gameSettings", JSON.stringify({
        viewMode: nextViewMode,
        language: "zh",
        seed: nextSeed,
        modelProvider: "anthropic",
        modelName: "deepseek-v4-flash",
        apiKey: "",
        baseUrl: "https://api.deepseek.com/anthropic",
        apiFormat: "anthropic_messages",
        authEnvVar: "ANTHROPIC_AUTH_TOKEN",
      }));
    },
    { nextViewMode: viewMode, nextSeed: seed },
  );
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
      NEXT_DIST_DIR: ".next-pause-probe",
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
  moderator: {},
  audience: {},
  consoleErrors: [],
  pageErrors: [],
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

  const moderatorPage = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  moderatorPage.on("console", (msg) => {
    if (msg.type() === "error") evidence.consoleErrors.push(`[moderator] ${msg.text().slice(0, 1000)}`);
  });
  moderatorPage.on("pageerror", (err) => evidence.pageErrors.push(`[moderator] ${String(err).slice(0, 1000)}`));

  await setViewMode(moderatorPage, frontendBase, "moderator", 23);
  const moderatorRoom = await createRoom(backendBase, "PauseProbeModerator", 23);
  await moderatorPage.goto(`${frontendBase}/room/${moderatorRoom.id}/play?mode=ai`, { waitUntil: "domcontentloaded" });
  await moderatorPage.getByTestId("global-pause-toggle").waitFor({ state: "visible", timeout: 40000 });

  const pauseButton = moderatorPage.getByTestId("global-pause-toggle");
  const labelBeforePause = (await pauseButton.innerText()).trim();
  await pauseButton.click();
  await moderatorPage.waitForFunction(
    () => document.querySelector('[data-testid="global-pause-toggle"]')?.textContent?.includes("继续"),
    { timeout: 15000 },
  );
  const pausedStatus = await (await fetch(`${backendBase}/api/rooms/${moderatorRoom.id}/control-status`)).json();
  const eventCountBeforeWait = await moderatorPage.locator('[data-testid="timeline-chat-bubble"]').count();
  await wait(1600);
  const eventCountAfterWait = await moderatorPage.locator('[data-testid="timeline-chat-bubble"]').count();
  await pauseButton.click();
  await moderatorPage.waitForFunction(
    () => document.querySelector('[data-testid="global-pause-toggle"]')?.textContent?.includes("暂停"),
    { timeout: 15000 },
  );
  const resumedStatus = await (await fetch(`${backendBase}/api/rooms/${moderatorRoom.id}/control-status`)).json();
  await moderatorPage.screenshot({ path: path.join(outputDir, "pause_control_moderator.png"), fullPage: true });

  evidence.moderator = {
    roomId: moderatorRoom.id,
    labelBeforePause,
    pausedStatus,
    resumedStatus,
    eventCountBeforeWait,
    eventCountAfterWait,
  };

  const audiencePage = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  audiencePage.on("console", (msg) => {
    if (msg.type() === "error") evidence.consoleErrors.push(`[audience] ${msg.text().slice(0, 1000)}`);
  });
  audiencePage.on("pageerror", (err) => evidence.pageErrors.push(`[audience] ${String(err).slice(0, 1000)}`));

  await setViewMode(audiencePage, frontendBase, "public", 24);
  const audienceRoom = await createRoom(backendBase, "PauseProbeAudience", 24);
  await audiencePage.goto(`${frontendBase}/room/${audienceRoom.id}/play?mode=ai`, { waitUntil: "domcontentloaded" });
  await wait(1800);
  const pauseButtonCount = await audiencePage.getByTestId("global-pause-toggle").count();
  await audiencePage.screenshot({ path: path.join(outputDir, "pause_control_audience.png"), fullPage: true });

  evidence.audience = {
    roomId: audienceRoom.id,
    pauseButtonCount,
  };
  evidence.assertions = {
    moderatorPauseVisible: labelBeforePause === "暂停",
    pauseApiPaused: pausedStatus?.paused === true,
    resumeApiUnpaused: resumedStatus?.paused === false,
    audiencePauseHidden: pauseButtonCount === 0,
    noConsoleErrors: evidence.consoleErrors.length === 0,
    noPageErrors: evidence.pageErrors.length === 0,
  };

  const evidencePath = path.join(outputDir, "pause_control_probe_evidence.json");
  await fs.writeFile(evidencePath, JSON.stringify(evidence, null, 2));

  if (!Object.values(evidence.assertions).every(Boolean)) {
    throw new Error(`Pause control probe failed: ${JSON.stringify(evidence.assertions)}`);
  }
  process.stdout.write(`Pause control probe passed. Evidence: ${path.relative(root, evidencePath)}\n`);
} finally {
  if (browser) await browser.close().catch(() => {});
  await terminateTree(frontend);
  await terminateTree(backend);
}
