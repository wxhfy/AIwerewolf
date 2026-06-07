#!/usr/bin/env node
/* Capture closure-report PNG screenshots with Playwright. */

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "..");
const assetsDir = path.join(root, "docs", "assets", "closure");
const screenshotsDir = path.join(assetsDir, "screenshots");
const manifestPath = path.join(assetsDir, "manifest.json");

function fileUrl(filePath) {
  return `file://${filePath}`;
}

async function screenshot(page, target, outFile, options = {}) {
  await page.setViewportSize(options.viewport || { width: 1440, height: 1100 });
  await page.goto(target, { waitUntil: "networkidle" });
  if (options.waitMs) {
    await page.waitForTimeout(options.waitMs);
  }
  if (options.selector) {
    const locator = page.locator(options.selector).first();
    await locator.waitFor({ state: "visible", timeout: 10000 });
    await locator.screenshot({ path: outFile, animations: "disabled" });
  } else {
    await page.screenshot({
      path: outFile,
      fullPage: options.fullPage ?? false,
      animations: "disabled",
    });
  }
  console.log(`[shot] ${path.relative(root, outFile)}`);
}

async function urlReachable(url) {
  try {
    const response = await fetch(url, { method: "GET" });
    return response.ok;
  } catch (_) {
    return false;
  }
}

async function main() {
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Missing ${manifestPath}; run scripts/generate_closure_visual_assets.py first.`);
  }
  fs.mkdirSync(screenshotsDir, { recursive: true });
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ deviceScaleFactor: 1 });

  const jobs = [
    {
      target: fileUrl(path.join(assetsDir, "real-game-snapshot.html")),
      out: path.join(screenshotsDir, "real-game-overview.png"),
      viewport: { width: 1500, height: 1120 },
      fullPage: true,
    },
    {
      target: fileUrl(path.join(assetsDir, "architecture.svg")),
      out: path.join(screenshotsDir, "architecture.png"),
      viewport: { width: 1160, height: 1020 },
      fullPage: false,
      selector: "svg",
    },
    {
      target: fileUrl(path.join(assetsDir, "play-evaluate-evolve.svg")),
      out: path.join(screenshotsDir, "play-evaluate-evolve.png"),
      viewport: { width: 1160, height: 560 },
      fullPage: false,
      selector: "svg",
    },
    {
      target: fileUrl(path.join(assetsDir, "database-evidence-chain.svg")),
      out: path.join(screenshotsDir, "database-evidence-chain.png"),
      viewport: { width: 980, height: 860 },
      fullPage: false,
      selector: "svg",
    },
    {
      target: fileUrl(path.join(assetsDir, "ai-werewolf-icon.svg")),
      out: path.join(screenshotsDir, "ai-werewolf-icon.png"),
      viewport: { width: 1024, height: 1024 },
      fullPage: false,
      selector: "svg",
    },
  ];

  if (manifest.assets.includes("strict-game-review.html")) {
    jobs.push({
      target: fileUrl(path.join(assetsDir, "strict-game-review.html")),
      out: path.join(screenshotsDir, "strict-game-review.png"),
      viewport: { width: 1440, height: 1100 },
      fullPage: false,
    });
  }

  const shouldCaptureFrontend = process.env.CAPTURE_FRONTEND_REVIEW === "1";
  const frontendBase = process.env.FRONTEND_URL || "http://127.0.0.1:3002";
  const frontendReportUrl = `${frontendBase.replace(/\/+$/, "")}/games/${manifest.game_id}/report`;
  if (shouldCaptureFrontend && await urlReachable(frontendReportUrl)) {
    jobs.push({
      target: frontendReportUrl,
      out: path.join(screenshotsDir, "frontend-review-page.png"),
      viewport: { width: 1440, height: 1100 },
      fullPage: false,
      waitMs: 1500,
    });
  } else if (shouldCaptureFrontend) {
    console.warn(`[warn] frontend report page not reachable: ${frontendReportUrl}`);
  }

  for (const job of jobs) {
    await screenshot(page, job.target, job.out, job);
  }

  await browser.close();

  const shotManifest = {
    game_id: manifest.game_id,
    generated_at: new Date().toISOString(),
    screenshots: jobs.map((job) => path.relative(root, job.out)),
    sources: manifest.sources,
  };
  fs.writeFileSync(path.join(screenshotsDir, "screenshots-manifest.json"), JSON.stringify(shotManifest, null, 2) + "\n");
  console.log(`[write] ${path.relative(root, path.join(screenshotsDir, "screenshots-manifest.json"))}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
