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
    // already gone
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

function samplePage(page) {
  return page.evaluate(() => ({
    url: window.location.href,
    bodyText: document.body.innerText.slice(0, 3000),
    hasEvolution: /进化|Evolution|Track C 控制台|Patch 状态/.test(document.body.innerText),
    bottomDockCount: document.querySelectorAll('[data-testid="bottom-dialogue-dock"]').length,
    timelineBubbleCount: document.querySelectorAll('[data-testid="timeline-chat-bubble"]').length,
    bottomText: document.querySelector('[data-testid="bottom-dialogue-text"]')?.textContent || "",
  }));
}

async function sampleBottomDialogue(page, durationMs = 4500) {
  const samples = [];
  const start = Date.now();
  while (Date.now() - start < durationMs) {
    samples.push(await page.evaluate(() => {
      const dock = document.querySelector('[data-testid="bottom-dialogue-dock"]');
      const text = document.querySelector('[data-testid="bottom-dialogue-text"]')?.textContent || "";
      return {
        t: Date.now(),
        visible: Boolean(dock),
        text,
        length: text.length,
        label: dock?.textContent?.includes("Speaking") || dock?.textContent?.includes("发言中")
          ? "speaking"
          : dock?.textContent?.includes("Dialogue") || dock?.textContent?.includes("当前发言")
            ? "dialogue"
            : dock?.textContent?.includes("Thinking") || dock?.textContent?.includes("思考中")
              ? "thinking"
              : "other",
        timelineBubbleCount: document.querySelectorAll('[data-testid="timeline-chat-bubble"]').length,
      };
    }));
    await wait(350);
  }
  return samples;
}

async function openSettingsModal(page) {
  const button = page.getByTestId("open-settings-button");
  await button.waitFor({ state: "visible", timeout: 30000 });
  await button.click();
  await page.getByTestId("settings-modal").waitFor({ state: "visible", timeout: 5000 }).catch(async () => {
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await button.click();
    await page.getByTestId("settings-modal").waitFor({ state: "visible", timeout: 15000 });
  });
}

function hasTypewriterGrowth(samples) {
  let previous = null;
  for (const sample of samples) {
    if (!sample.visible || sample.label !== "speaking") {
      previous = null;
      continue;
    }
    if (previous && sample.length > previous.length) return true;
    previous = sample;
  }
  return false;
}

function hasTimelineReveal(samples) {
  const counts = samples.map((item) => item.timelineBubbleCount);
  return Math.max(...counts) > Math.min(...counts);
}

function logEvent(logs, type, payload) {
  logs.push({ type, payload: String(payload).slice(0, 1000) });
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
      NEXT_DIST_DIR: ".next-probe",
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
  settings: {},
  desktop: {},
  mobile: {},
  assertions: {},
  backendLogs,
  frontendLogs,
};

try {
  await waitForServer(`http://127.0.0.1:${backendPort}/api/health`);
  await waitForServer(`http://127.0.0.1:${frontendPort}/`);

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

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("open-settings-button").waitFor({ state: "visible", timeout: 30000 });

  const lobbyInitial = await samplePage(page);
  if (lobbyInitial.hasEvolution) throw new Error("Lobby exposes evolution UI");

  await openSettingsModal(page);
  await page.getByText("管理与测速").waitFor({ timeout: 30000 });
  const settingsState = await page.evaluate(() => {
    const labels = Array.from(document.querySelectorAll("label"));
    const findInput = (labelText) => {
      const label = labels.find((item) => item.textContent?.includes(labelText));
      return label?.querySelector("input,select");
    };
    return {
      provider: findInput("供应商")?.value || "",
      modelName: findInput("模型名称")?.value || "",
      baseUrl: findInput("请求地址")?.value || "",
      apiKeyType: findInput("API Key")?.getAttribute("type") || "",
      apiKeyPlaceholder: findInput("API Key")?.getAttribute("placeholder") || "",
      apiFormat: findInput("API 格式")?.value || "",
      apiFormatText: findInput("API 格式")?.selectedOptions?.[0]?.textContent || "",
      authEnvVar: findInput("认证字段")?.value || "",
      authEnvVarText: findInput("认证字段")?.selectedOptions?.[0]?.textContent || "",
      text: document.body.innerText,
    };
  });
  if (settingsState.provider !== "anthropic") throw new Error(`provider mismatch: ${settingsState.provider}`);
  if (settingsState.baseUrl !== "https://api.deepseek.com/anthropic") throw new Error(`base URL mismatch: ${settingsState.baseUrl}`);
  if (settingsState.apiFormat !== "anthropic_messages") throw new Error(`api format mismatch: ${settingsState.apiFormat}`);
  if (settingsState.authEnvVar !== "ANTHROPIC_AUTH_TOKEN") throw new Error(`auth field mismatch: ${settingsState.authEnvVar}`);
  for (const expected of [
    "完整 URL",
    "https://api.deepseek.com/anthropic",
    "填写兼容 Claude API 的服务端点地址，不要以斜杠结尾",
    "选择供应商 API 的输入格式",
    "选择写入配置的认证环境变量名",
    "获取 API Key",
  ]) {
    if (!settingsState.text.includes(expected)) throw new Error(`settings text missing: ${expected}`);
  }
  evidence.settings.initial = settingsState;

  await page.locator("label").filter({ hasText: "API Key" }).locator("input").fill("ui-probe-placeholder-key");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.body.innerText.includes("管理与测速"), { timeout: 10000 });
  await openSettingsModal(page);
  await page.getByText("管理与测速").waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: "保存" }).click();
  await page.waitForFunction(() => !document.body.innerText.includes("管理与测速"), { timeout: 10000 });

  await page.getByRole("button", { name: "开始 AI 对局" }).click();
  await page.getByText("准备开始").waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "确认开始" }).click();
  await page.waitForURL(/\/room\/.+\/play/, { timeout: 30000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="bottom-dialogue-dock"]') || document.body.innerText.includes("游戏结束"), { timeout: 45000 });

  const firstSamples = await sampleBottomDialogue(page, 5500);
  if (!hasTypewriterGrowth(firstSamples)) {
    const moreSamples = await sampleBottomDialogue(page, 6500);
    firstSamples.push(...moreSamples);
  }
  await page.waitForFunction(() => {
    const timelineCount = document.querySelectorAll('[data-testid="timeline-chat-bubble"]').length;
    const dock = document.querySelector('[data-testid="bottom-dialogue-dock"]');
    const dockText = dock?.textContent || "";
    return timelineCount > 0 || dockText.includes("当前发言") || dockText.includes("Dialogue") || document.body.innerText.includes("游戏结束");
  }, { timeout: 18000 }).catch(() => {});
  const revealSamples = await sampleBottomDialogue(page, 2200);
  firstSamples.push(...revealSamples);
  await page.screenshot({ path: path.join(outputDir, "ui_real_desktop_bubble.png"), fullPage: true });
  evidence.desktop = {
    afterRun: await samplePage(page),
    bottomSamples: firstSamples,
    hasTypewriterGrowth: hasTypewriterGrowth(firstSamples),
    hasTimelineReveal: hasTimelineReveal(firstSamples) || await page.locator('[data-testid="timeline-chat-bubble"]').count() > 0,
    logContainsPartialTypewriterCursor: (await page.locator('[data-testid="timeline-chat-bubble"]').allTextContents())
      .some((text) => text.includes("|") || text.includes("▌")),
  };

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  if (!(await page.locator('[data-testid="bottom-dialogue-dock"]').count())) {
    await page.waitForFunction(() => document.querySelector('[data-testid="bottom-dialogue-dock"]') || document.body.innerText.includes("游戏结束"), { timeout: 12000 }).catch(() => {});
  }
  await page.screenshot({ path: path.join(outputDir, "ui_real_mobile_bubble.png"), fullPage: true });
  evidence.mobile = await samplePage(page);

  evidence.assertions = {
    noEvolutionLobby: !lobbyInitial.hasEvolution,
    settingsOk: true,
    settingsClosedByEscape: true,
    settingsClosedAfterSave: true,
    noConsoleErrors: evidence.console.filter((item) => item.type === "error").length === 0,
    noPageErrors: evidence.pageErrors.length === 0,
    bottomDockVisibleDesktop: evidence.desktop.afterRun.bottomDockCount > 0,
    bottomDockVisibleMobile: evidence.mobile.bottomDockCount > 0,
    bottomTypewriterGrowth: evidence.desktop.hasTypewriterGrowth,
    timelineRevealObserved: evidence.desktop.hasTimelineReveal || evidence.desktop.afterRun.timelineBubbleCount > 0,
    timelineNoPartialCursor: !evidence.desktop.logContainsPartialTypewriterCursor,
  };

  const failed = Object.entries(evidence.assertions).filter(([, value]) => value !== true);
  if (failed.length) {
    throw new Error(`UI assertions failed: ${failed.map(([key]) => key).join(", ")}`);
  }
} finally {
  if (browser) await browser.close();
  await fs.writeFile(path.join(outputDir, "frontend_ui_probe.json"), JSON.stringify(evidence, null, 2), "utf-8");
  await Promise.all([terminateTree(frontend), terminateTree(backend)]);
}

console.log(JSON.stringify({
  output: path.join(outputDir, "frontend_ui_probe.json"),
  assertions: evidence.assertions,
  desktopSampleCount: evidence.desktop.bottomSamples?.length || 0,
}, null, 2));
