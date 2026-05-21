import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForServer(url, retries = 80) {
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

const port = 8010;
const server = spawn(
  "python",
  ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", String(port)],
  {
    stdio: "inherit",
    env: { ...process.env, PYTHONPATH: process.cwd() },
  }
);

let browser;
try {
  await waitForServer(`http://127.0.0.1:${port}/api/health`);

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });

  await page.goto(`http://127.0.0.1:${port}/?lang=zh`, { waitUntil: "networkidle" });
  await page.waitForSelector("#run");
  await page.click("#lang-en");
  await page.waitForFunction(() => document.documentElement.lang === "en");
  await page.fill("#seed", "11");
  await page.fill("#speed", "0");
  await page.click("#run");
  await page.waitForFunction(() => {
    const winner = document.querySelector("#winner");
    return winner && winner.textContent && winner.textContent !== "-" && winner.textContent !== "...";
  }, { timeout: 30000 });

  const stateAfterRun = await page.evaluate(() => ({
    lang: document.documentElement.lang,
    roomLabel: document.querySelector("#room-label")?.textContent,
    gameLabel: document.querySelector("#game-label")?.textContent,
    title: document.querySelector("h1")?.textContent,
    winner: document.querySelector("#winner")?.textContent,
    day: document.querySelector("#day")?.textContent,
    events: document.querySelector("#event-count")?.textContent,
    players: document.querySelectorAll(".player").length,
    timeline: document.querySelectorAll(".event").length,
    status: document.querySelector("#status-title")?.textContent,
  }));

  if (stateAfterRun.lang !== "en") throw new Error(`Language switch failed: ${stateAfterRun.lang}`);
  if (!["Village", "Wolves"].includes(stateAfterRun.winner)) throw new Error(`Unexpected winner text: ${stateAfterRun.winner}`);
  if (!stateAfterRun.roomLabel || stateAfterRun.roomLabel.endsWith("-")) throw new Error(`Room label not initialized: ${stateAfterRun.roomLabel}`);
  if (!stateAfterRun.gameLabel || stateAfterRun.gameLabel.endsWith("-")) throw new Error(`Game label not initialized: ${stateAfterRun.gameLabel}`);
  if (Number(stateAfterRun.players) !== 7) throw new Error(`Expected 7 players, got ${stateAfterRun.players}`);
  if (Number(stateAfterRun.timeline) < 20) throw new Error(`Expected timeline events, got ${stateAfterRun.timeline}`);

  await page.click("#private");
  await page.waitForFunction(() => {
    const roles = Array.from(document.querySelectorAll(".role")).map((node) => node.textContent || "");
    return roles.some((text) => text.includes("Werewolf") || text.includes("Seer"));
  }, { timeout: 30000 });

  const moderatorView = await page.evaluate(() => ({
    buttonText: document.querySelector("#private")?.textContent,
    roleTexts: Array.from(document.querySelectorAll(".role")).map((node) => node.textContent || ""),
    timeline: document.querySelectorAll(".event").length,
  }));

  if (moderatorView.buttonText !== "Public View") throw new Error(`Moderator toggle failed: ${moderatorView.buttonText}`);
  if (!moderatorView.roleTexts.some((text) => text.includes("Werewolf") || text.includes("Seer"))) {
    throw new Error("Moderator view did not reveal roles");
  }

  console.log("UI smoke passed", JSON.stringify(stateAfterRun), JSON.stringify(moderatorView));
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
