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

async function waitForLengthGrowth(locator, timeout = 5000) {
  await locator.waitFor({ timeout });
  const first = ((await locator.textContent()) || "").trim().length;
  await wait(500);
  const second = ((await locator.textContent()) || "").trim().length;
  await wait(900);
  const third = ((await locator.textContent()) || "").trim().length;
  if (!(third > first || second > first)) {
    throw new Error(`Bottom dialogue text did not grow: ${first} -> ${second} -> ${third}`);
  }
}

const backendPort = await getFreePort();
const frontendPort = await getFreePort();
const pythonBin = process.env.PYTHON || "python";
const nextDistDir = process.env.NEXT_DIST_DIR || ".next-smoke";

const backend = spawn(
  pythonBin,
  ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(backendPort)],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      _TEST_ALLOW_FAKE_LLM: "true",
      PYTHONPATH: process.cwd(),
      LLM_PROVIDER: "fake",
      AIWEREWOLF_DEFAULT_AGENT_TYPE: "llm",
      MODEL_POOL: "fake:fake-llm",
      DOUBAO_MODEL_POOL: "fake:fake-llm",
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
      NEXT_DIST_DIR: nextDistDir,
    },
  }
);

let browser;
try {
  await waitForServer(`http://127.0.0.1:${backendPort}/api/health`);
  await waitForServer(`http://127.0.0.1:${frontendPort}/`);

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: "角色库" }).waitFor({ timeout: 30000 });
  if (await page.getByRole("link", { name: /进化看板|Evolution/ }).isVisible().catch(() => false)) {
    throw new Error("Lobby still exposes the evolution page link");
  }
  await page.getByRole("button", { name: "设置" }).click();
  await page.getByText("管理与测速").waitFor({ timeout: 30000 });
  await page.getByLabel("请求地址").waitFor({ timeout: 30000 });
  const baseUrlValue = await page.getByLabel("请求地址").inputValue();
  if (baseUrlValue !== "https://api.deepseek.com/anthropic") {
    throw new Error(`Unexpected request address: ${baseUrlValue}`);
  }
  await page.getByText("完整 URL").waitFor();
  await page.getByText("https://api.deepseek.com/anthropic").waitFor();
  await page.getByText("填写兼容 Claude API 的服务端点地址，不要以斜杠结尾").waitFor();
  await page.getByLabel("API 格式").waitFor();
  const apiFormat = await page.getByLabel("API 格式").inputValue();
  if (apiFormat !== "anthropic_messages") {
    throw new Error(`Unexpected API format: ${apiFormat}`);
  }
  const apiFormatLabel = await page.getByLabel("API 格式").locator("option:checked").textContent();
  if (!apiFormatLabel?.includes("Anthropic Messages")) {
    throw new Error(`Unexpected API format label: ${apiFormatLabel}`);
  }
  await page.getByText("选择供应商 API 的输入格式").waitFor();
  await page.getByLabel("认证字段").waitFor();
  const authField = await page.getByLabel("认证字段").inputValue();
  if (authField !== "ANTHROPIC_AUTH_TOKEN") {
    throw new Error(`Unexpected auth field: ${authField}`);
  }
  const authFieldLabel = await page.getByLabel("认证字段").locator("option:checked").textContent();
  if (!authFieldLabel?.includes("ANTHROPIC_AUTH_TOKEN")) {
    throw new Error(`Unexpected auth field label: ${authFieldLabel}`);
  }
  await page.getByText("选择写入配置的认证环境变量名").waitFor();
  await page.getByRole("link", { name: "获取 API Key" }).waitFor();
  await page.getByRole("button", { name: "保存" }).click();
  await page.goto(`http://127.0.0.1:${frontendPort}/eval/dashboard?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.getByText("Track B 评估总览").waitFor({ timeout: 30000 });
  if (await page.getByText(/前往 Track C 控制台|进化轮次|Patch 状态分布|B\/C 验收门通过率/).isVisible().catch(() => false)) {
    throw new Error("Eval dashboard still exposes evolution UI");
  }

  const completedRoomResponse = await fetch(
    `http://127.0.0.1:${backendPort}/api/rooms?name=SmokeReview&seed=34&player_count=7&agent_type=llm`,
    { method: "POST" }
  );
  const completedRoom = await completedRoomResponse.json();
  const completedGameResponse = await fetch(`http://127.0.0.1:${backendPort}/api/rooms/${completedRoom.id}/games?show_private=true`, { method: "POST" });
  const completedGame = await completedGameResponse.json();
  const completedSnapshotResponse = await fetch(`http://127.0.0.1:${backendPort}/api/rooms/${completedRoom.id}/snapshot?show_private=true`);
  const completedSnapshot = await completedSnapshotResponse.json();
  if (completedSnapshot.phase !== "GAME_END" || !completedSnapshot.winner) {
    throw new Error("Completed room snapshot did not reach GAME_END");
  }

  await page.goto(`http://127.0.0.1:${frontendPort}/room/${completedRoom.id}/play?mode=ai&lang=en`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(({ roomId }) => {
    const text = document.body.innerText;
    return window.location.pathname.includes(`/room/${roomId}/play`) && text.length > 0;
  }, { roomId: completedRoom.id }, { timeout: 30000 });

  const reviewState = await page.evaluate(() => ({
    text: document.body.innerText,
    url: window.location.pathname,
  }));
  if (!reviewState.url.includes(`/room/${completedRoom.id}/play`)) {
    throw new Error(`Completed room route missing: ${reviewState.url}`);
  }
  const gameId = completedGame.id;
  if (!gameId) throw new Error("Completed room did not include a latest game id");

  await page.goto(`http://127.0.0.1:${frontendPort}/games/${gameId}/report?lang=en`, { waitUntil: "domcontentloaded" });
  await page.getByText(/Game Review|对局复盘/).waitFor({ timeout: 30000 });
  await page.locator("iframe").waitFor({ timeout: 30000 });

  const htmlPage = await browser.newPage();
  const htmlUrl = `http://127.0.0.1:${backendPort}/api/games/${gameId}/reviews/html`;
  await htmlPage.goto(htmlUrl, { waitUntil: "domcontentloaded" });
  const htmlText = await htmlPage.textContent("body");
  if (!htmlText?.includes("AI Werewolf 复盘报告")) {
    throw new Error("HTML review page did not render the exported report");
  }
  const hasSvgVisual = await htmlPage.locator("svg").count();
  if (!hasSvgVisual) {
    throw new Error("HTML review page did not render visual-agent SVG assets");
  }
  await htmlPage.close();
  if (await page.getByRole("link", { name: /进化看板|Evolution/ }).isVisible().catch(() => false)) {
    throw new Error("Game review page still exposes the evolution link");
  }

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=zh`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "设置" }).click();
  await page.getByRole("button", { name: /EN|English/ }).click();
  await page.getByRole("button", { name: /Save|保存/ }).click();
  await page.getByText("Game Mode").waitFor();
  await page.getByRole("button", { name: "Start AI Match" }).waitFor();

  await page.getByRole("button", { name: "Start AI Match" }).click();
  await page.getByText("Ready to Start").waitFor();
  await page.getByRole("button", { name: "Confirm & Start" }).click();
  await page.waitForURL(/\/room\/.+\/play/);
  const runButton = page.getByRole("button", { name: "Run Game" });
  if (await runButton.isVisible().catch(() => false)) {
    await runButton.click();
  }
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return (
      text.includes("Match in progress") ||
      /Day\s+\d+/.test(text) ||
      text.includes("Game Over") ||
      text.includes("游戏结束") ||
      text.includes("View Review") ||
      text.includes("查看复盘")
    );
  }, { timeout: 30000 });
  await page.waitForFunction(() => {
    const text = document.body.innerText;
    return (
      text.includes("Events") ||
      text.includes("事件") ||
      text.includes("Game started") ||
      text.includes("对局开始") ||
      text.includes("Exile Vote") ||
      text.includes("放逐投票") ||
      text.includes("Dialogue") ||
      text.includes("当前发言") ||
      text.includes("View Review") ||
      text.includes("查看复盘")
    );
  }, { timeout: 30000 });
  const bottomDock = page.getByTestId("bottom-dialogue-dock");
  const bottomDialogueText = page.getByTestId("bottom-dialogue-text");
  const bottomDialogueVisible = await bottomDock.isVisible().catch(() => false);
  if (bottomDialogueVisible) {
    const timelineBefore = await page.getByTestId("timeline-chat-bubble").count();
    const dockText = (await bottomDock.textContent()) || "";
    const isSpeaking = dockText.includes("Speaking") || dockText.includes("发言中");
    if (isSpeaking) {
      await waitForLengthGrowth(bottomDialogueText);
      await page.waitForFunction(() => {
        const dock = document.querySelector('[data-testid="bottom-dialogue-dock"]');
        return dock?.textContent?.includes("Dialogue") || dock?.textContent?.includes("当前发言");
      }, { timeout: 12000 });
    }
    const timelineAfter = await page.getByTestId("timeline-chat-bubble").count();
    if (isSpeaking && timelineAfter <= timelineBefore) {
      throw new Error(`Timeline chat did not reveal after bottom dialogue completed: ${timelineBefore} -> ${timelineAfter}`);
    }
  }
  const aiState = await page.evaluate(() => ({
    url: window.location.pathname,
    text: document.body.innerText,
  }));

  if (!aiState.url.includes("/room/")) throw new Error(`AI room route missing: ${aiState.url}`);
  if (
    !aiState.text.includes("Run Game") &&
    !aiState.text.includes("Match in progress") &&
    !aiState.text.includes("Game Over") &&
    !aiState.text.includes("View Review") &&
    !aiState.text.includes("Game started") &&
    !aiState.text.includes("Exile Vote") &&
    !aiState.text.includes("Dialogue") &&
    !/Day\s+\d+/.test(aiState.text)
  ) {
    throw new Error("AI play page did not render expected controls or match state");
  }

  await page.goto(`http://127.0.0.1:${frontendPort}/?lang=en`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /Human Play|真人参与/ }).click();
  await page.getByText(/Your Seat|你的座位号/).waitFor();
  await page.locator("button").filter({ hasText: /Start .*Match|开始.*对局/ }).last().click();
  await page.getByText(/Ready to Start|准备开始/).waitFor();

  const humanRoomResponse = await fetch(
    `http://127.0.0.1:${backendPort}/api/rooms?name=HumanSmoke&seed=1&player_count=7&agent_type=llm&human_seat=1`,
    { method: "POST" }
  );
  const humanRoom = await humanRoomResponse.json();
  await fetch(`http://127.0.0.1:${backendPort}/api/rooms/${humanRoom.id}/start?show_private=true`, { method: "POST" });
  await page.goto(`http://127.0.0.1:${frontendPort}/room/${humanRoom.id}/play?human_seat=1&mode=human`, { waitUntil: "domcontentloaded" });
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
