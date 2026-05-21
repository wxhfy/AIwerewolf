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

  await page.selectOption("#mode-select", "ai");
  await page.selectOption("#agent-type", "heuristic");
  await page.click("#run");
  await page.waitForFunction(() => {
    const winner = document.querySelector("#winner-text");
    return winner && winner.textContent && winner.textContent !== "-";
  }, { timeout: 30000 });

  const aiState = await page.evaluate(() => ({
    lang: document.documentElement.lang,
    room: document.querySelector("#status-room")?.textContent,
    winner: document.querySelector("#winner-text")?.textContent,
    day: document.querySelector("#status-day")?.textContent,
    timeline: document.querySelectorAll(".speech-entry, .vote-entry").length,
    players: document.querySelectorAll(".player-card").length,
  }));

  if (aiState.lang !== "en") throw new Error(`Language switch failed: ${aiState.lang}`);
  if (!["Village", "Wolves"].includes(aiState.winner)) throw new Error(`Unexpected winner text: ${aiState.winner}`);
  if (!aiState.room || aiState.room.endsWith("-")) throw new Error(`Room label not initialized: ${aiState.room}`);
  if (Number(aiState.players) !== 7) throw new Error(`Expected 7 players, got ${aiState.players}`);
  if (Number(aiState.timeline) < 10) throw new Error(`Expected timeline events, got ${aiState.timeline}`);

  await page.click("#private");
  await page.waitForFunction(() => {
    const roles = Array.from(document.querySelectorAll(".player-role")).map((node) => node.textContent || "");
    return roles.some((text) => text.includes("Werewolf") || text.includes("Seer"));
  }, { timeout: 10000 });

  await page.selectOption("#mode-select", "human");
  await page.selectOption("#human-seat", "1");
  await page.waitForTimeout(800);
  await page.click("#run");
  await page.waitForSelector("#action-panel:not(.hidden)", { timeout: 30000 });

  const humanState = await page.evaluate(() => ({
    actionTitle: document.querySelector("#action-title")?.textContent,
    actionPrompt: document.querySelector("#action-prompt")?.textContent,
    room: document.querySelector("#status-room")?.textContent,
    phase: document.querySelector("#status-phase")?.textContent,
  }));

  if (!humanState.actionPrompt) throw new Error("Human action prompt did not render");
  if (!humanState.room || !humanState.room.includes("Seat")) throw new Error(`Human room seat not rendered: ${humanState.room}`);

  console.log("UI smoke passed", JSON.stringify(aiState), JSON.stringify(humanState));
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
}
