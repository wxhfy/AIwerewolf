import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import net from "node:net";

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
      server.close(() => {
        if (port) resolve(port);
        else reject(new Error("Unable to allocate a free port"));
      });
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

async function waitForServer(url, retries = 120) {
  for (let i = 0; i < retries; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
    }
    await wait(250);
  }
  throw new Error(`Server did not become ready: ${url}`);
}

const backendPort = await getFreePort();
const frontendPort = await getFreePort();

const backend = spawn(
  "python",
  ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      PYTHONPATH: process.cwd(),
      LLM_PROVIDER: "fake",
      AIWEREWOLF_DEFAULT_AGENT_TYPE: "llm",
    },
  }
);

const frontend = spawn(
  "npx",
  ["next", "dev", "-p", String(frontendPort)],
  {
    cwd: `${process.cwd()}/frontend`,
    stdio: "inherit",
    env: {
      ...process.env,
      BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
      NEXT_PUBLIC_BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
    },
  }
);

let browser;
try {
  await waitForServer(`http://127.0.0.1:${backendPort}/api/health`);
  await waitForServer(`http://127.0.0.1:${frontendPort}/`);

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });

  await page.goto(`http://127.0.0.1:${frontendPort}/evolution?lang=en`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return text.includes("Evolution Dashboard") || text.includes("自进化控制台");
  }, { timeout: 30000 });
  await page.getByRole("button", { name: /Run 20-Seed A\/B|运行 20 Seed A\/B/ }).waitFor({ timeout: 30000 });
  await page.getByText(/Knowledge Wiki|策略知识库/).waitFor({ timeout: 30000 });

  const completedRoomResponse = await fetch(
    `http://127.0.0.1:${backendPort}/api/rooms?name=SmokeReview&seed=34&player_count=7&agent_type=llm`,
    { method: "POST" }
  );
  const completedRoom = await completedRoomResponse.json();
  await fetch(`http://127.0.0.1:${backendPort}/api/rooms/${completedRoom.id}/games?show_private=true`, { method: "POST" });

  await page.goto(`http://127.0.0.1:${frontendPort}/room/${completedRoom.id}/play?mode=ai&lang=en`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return (
      (text.includes("Track B Review") || text.includes("Track B 复盘")) &&
      (text.includes("Validated and published") || text.includes("已通过校验并发布"))
    );
  }, { timeout: 30000 });

  const reviewState = await page.evaluate(() => ({
    text: document.body.innerText,
    url: window.location.pathname,
  }));
  if (!reviewState.url.includes(`/room/${completedRoom.id}/play`)) {
    throw new Error(`Completed room route missing: ${reviewState.url}`);
  }
  if (
    !reviewState.text.includes("Scoreboard") &&
    !reviewState.text.includes("玩家评分榜") &&
    !reviewState.text.includes("Track B Review") &&
    !reviewState.text.includes("Track B 复盘")
  ) {
    throw new Error("Completed room did not render the Track B review panel");
  }
  const htmlLink = page.getByRole("link", { name: /Open HTML Report|打开 HTML 报告/ });
  const htmlHref = await htmlLink.getAttribute("href");
  if (!htmlHref || !htmlHref.includes(`/api/games/`)) {
    throw new Error("HTML review link was not rendered");
  }
  const htmlPage = await browser.newPage();
  const htmlUrl = htmlHref.startsWith("http") ? htmlHref : `http://127.0.0.1:${frontendPort}${htmlHref}`;
  await htmlPage.goto(htmlUrl, { waitUntil: "networkidle" });
  const htmlText = await htmlPage.textContent("body");
  if (!htmlText?.includes("AI Werewolf 复盘报告")) {
    throw new Error("HTML review page did not render the exported report");
  }
  const hasSvgVisual = await htmlPage.locator("svg").count();
  if (!hasSvgVisual) {
    throw new Error("HTML review page did not render visual-agent SVG assets");
  }
  await htmlPage.close();

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=zh`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "EN" }).click();
  await page.getByText("Configure your game and start an AI Werewolf match").waitFor();

  await page.getByRole("button", { name: "Start Game" }).click();
  await page.getByText("Ready to Start").waitFor();
  await page.getByRole("button", { name: "Confirm & Start" }).click();
  await page.waitForURL(/\/room\/.+\/play/);
  const runButton = page.getByRole("button", { name: "Run Game" });
  if (await runButton.isVisible().catch(() => false)) {
    await runButton.click();
  }
  await page.waitForFunction(() => document.body.innerText.includes("Match in progress") || /Day\\s+\\d+/.test(document.body.innerText), { timeout: 30000 });
  await page.waitForFunction(() => document.body.innerText.includes("events") || document.body.innerText.includes("Events"), { timeout: 30000 });
  const aiState = await page.evaluate(() => ({
    url: window.location.pathname,
    text: document.body.innerText,
  }));

  if (!aiState.url.includes("/room/")) throw new Error(`AI room route missing: ${aiState.url}`);
  if (!aiState.text.includes("Run Game") && !aiState.text.includes("Match in progress") && !/Day\s+\d+/.test(aiState.text)) {
    throw new Error("AI play page did not render expected controls or match state");
  }

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=en`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Human Play|真人参与/ }).click();
  await page.getByText(/Your Seat|你的座位号/).waitFor();
  await page.getByRole("button", { name: /Start Game|开始游戏/ }).click();
  await page.getByText(/Ready to Start|准备开始/).waitFor();

  const humanRoomResponse = await fetch(
    `http://127.0.0.1:${backendPort}/api/rooms?name=HumanSmoke&seed=1&player_count=7&agent_type=llm&human_seat=1`,
    { method: "POST" }
  );
  const humanRoom = await humanRoomResponse.json();
  await fetch(`http://127.0.0.1:${backendPort}/api/rooms/${humanRoom.id}/start?show_private=true`, { method: "POST" });
  await page.goto(`http://127.0.0.1:${frontendPort}/room/${humanRoom.id}/play?human_seat=1&mode=human`, { waitUntil: "networkidle" });
  await page.waitForURL(/mode=human/, { timeout: 60000 });
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return (
      text.includes("Submit") ||
      text.includes("提交") ||
      text.includes("Please select a target") ||
      text.includes("请选择目标") ||
      text.includes("Your turn") ||
      text.includes("轮到")
    );
  }, { timeout: 60000 });

  console.log("UI smoke passed");
} finally {
  if (browser) await browser.close();
  await Promise.all([terminateProcess(frontend), terminateProcess(backend)]);
}
