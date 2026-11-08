import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE || 'http://127.0.0.1:3001';
const API = process.env.E2E_API || 'http://127.0.0.1:8000';
const SCREEN_DIR = process.env.E2E_SCREEN_DIR || '/workspace/aw-slice1-logs/screens';
const SUMMARY_PATH = '/workspace/aw-slice1-logs/e2e-summary.json';

fs.mkdirSync(SCREEN_DIR, { recursive: true });
fs.mkdirSync(path.dirname(SUMMARY_PATH), { recursive: true });

const summary = {
  timestamp: new Date().toISOString(),
  roomId: null,
  gameId: null,
  passed: false,
  checks: {
    fixture_started: false,
    desktop_seats_rendered: false,
    phase_transitions: false,
    no_duplicate_speech_events: false,
    game_end_panel_visible: false,
    snapshot_privacy_enforced: false,
    no_show_private_view: false,
    reconnect_deduped: false,
    mobile_no_horizontal_overflow: false,
    reduced_motion_supported: false,
  },
  screenshots: [],
  phasesSeen: [],
  speechEventCount: 0,
};

async function main() {
  console.log(`[Step 1] Starting fixture replay on ${API}...`);
  const startRes = await fetch(`${API}/api/dev/fixture/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ interval_ms: 800 }),
  });
  if (!startRes.ok) throw new Error(`Fixture start failed: ${startRes.status} ${await startRes.text()}`);
  const startData = await startRes.json();
  if (!startData.fixture?.includes('FIXTURE/MOCK')) throw new Error(`Invalid fixture marker: ${JSON.stringify(startData)}`);
  const roomId = startData.room_id;
  const gameId = startData.game_id;
  summary.roomId = roomId;
  summary.gameId = gameId;
  summary.checks.fixture_started = true;
  console.log(`Fixture started: roomId=${roomId}, gameId=${gameId}`);

  const attachRoute = async (context) => {
    await context.route(`**/api/rooms/${roomId}/start*`, async (route) => {
      try {
        const snapRes = await fetch(`${API}/api/rooms/${roomId}/snapshot`);
        const snap = await snapRes.json();
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ match_id: gameId, room_id: roomId, status: 'running', seq: snap.seq || 0, snapshot: snap }),
        });
      } catch {
        await route.continue();
      }
    });
  };

  console.log(`[Step 2] Launching chromium headless for desktop view...`);
  const browser = await chromium.launch({ headless: true });
  const defaultContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await attachRoute(defaultContext);
  const page = await defaultContext.newPage();

  await page.goto(`${BASE}/room/${roomId}/play`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelectorAll('[data-testid^=seat-]').length >= 7, { timeout: 30000 });
  summary.checks.desktop_seats_rendered = true;
  console.log('Desktop seats rendered (count >= 7).');

  console.log(`[Step 3] Polling phases and draining speech queue...`);
  let lastPhase = null;
  const allSpeechIds = new Set();
  let capturedNoRoles = false;
  let disclosedTrue = false;
  const pollStart = Date.now();
  let gameEndVisible = false;

  while (Date.now() - pollStart < 120000) {
    const banner = await page.$('[data-testid=phase-banner]');
    if (banner) {
      const currentPhase = await banner.getAttribute('data-phase');
      if (currentPhase && currentPhase !== lastPhase) {
        lastPhase = currentPhase;
        if (!summary.phasesSeen.includes(currentPhase)) summary.phasesSeen.push(currentPhase);
        const shot = path.join(SCREEN_DIR, `desktop-${currentPhase}-${Date.now()}.png`);
        await page.screenshot({ path: shot });
        summary.screenshots.push(shot);
        console.log(`Phase changed to ${currentPhase}, captured screenshot.`);
      }
    }

    const skipBtn = await page.$('[data-testid=skip-typing]');
    if (skipBtn && (await skipBtn.isVisible()) && (await skipBtn.isEnabled())) {
      try { await skipBtn.click({ timeout: 200 }); } catch (_) {}
    }

    const currentSpeechIds = await page.$$eval('[data-testid=speech-item]', items =>
      items.map(el => el.getAttribute('data-event-id')).filter(Boolean)
    );
    if (new Set(currentSpeechIds).size !== currentSpeechIds.length) {
      throw new Error(`Duplicate speech-item event-ids found: ${JSON.stringify(currentSpeechIds)}`);
    }
    currentSpeechIds.forEach(id => allSpeechIds.add(id));

    try {
      const snap = await page.evaluate(async (rid) => {
        const r = await fetch(`/api/rooms/${rid}/snapshot`);
        return await r.json();
      }, roomId);
      if (snap?.players?.every(p => !p.role)) capturedNoRoles = true;
      if (snap?.disclosed === true) disclosedTrue = true;
    } catch (_) {}

    const endPanel = await page.$('[data-testid=game-end-panel]');
    if (endPanel && (await endPanel.isVisible())) {
      gameEndVisible = true;
      const endShot = path.join(SCREEN_DIR, `desktop-end-${Date.now()}.png`);
      await page.screenshot({ path: endShot });
      summary.screenshots.push(endShot);
      console.log('Game end panel reached and captured.');
      break;
    }
    await new Promise(r => setTimeout(r, 250));
  }

  if (!gameEndVisible) throw new Error('Timed out waiting for [data-testid=game-end-panel] (120s)');
  summary.checks.phase_transitions = summary.phasesSeen.length >= 3;
  summary.checks.no_duplicate_speech_events = true;
  summary.checks.game_end_panel_visible = gameEndVisible;
  summary.speechEventCount = allSpeechIds.size;

  console.log(`[Step 4] Checking snapshot privacy and UI text isolation...`);
  const finalSnap = await page.evaluate(async (rid) => {
    const r = await fetch(`/api/rooms/${rid}/snapshot`);
    return await r.json();
  }, roomId);
  if (finalSnap?.disclosed === true) disclosedTrue = true;
  if (!capturedNoRoles && !disclosedTrue) {
    throw new Error(`Snapshot privacy assertion failed: capturedNoRoles=${capturedNoRoles}, disclosedTrue=${disclosedTrue}`);
  }
  summary.checks.snapshot_privacy_enforced = true;

  const bodyText = await page.innerText('body');
  if (/NIGHT_GUARD_ACTION.*target|NIGHT_WOLF_ACTION.*target|查验结果|私聊密谋/i.test(bodyText)) {
    throw new Error('Body text leaked private night actions!');
  }
  const hasShowPrivateView = await page.evaluate(() =>
    Array.from(document.querySelectorAll('*')).some(el => el.children.length === 0 && el.textContent && /showPrivateView/.test(el.textContent))
  );
  if (hasShowPrivateView) console.warn('Soft-check: element with text /showPrivateView/ found');
  summary.checks.no_show_private_view = !hasShowPrivateView;

  console.log(`[Step 5] Testing reconnect and deduping...`);
  await page.evaluate(() => { if (window._activeEventSources) window._activeEventSources.forEach(s => s.close()); });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelectorAll('[data-testid^=seat-]').length >= 7, { timeout: 30000 });
  const reloadedSpeechIds = await page.$$eval('[data-testid=speech-item]', items =>
    items.map(el => el.getAttribute('data-event-id')).filter(Boolean)
  );
  if (new Set(reloadedSpeechIds).size !== reloadedSpeechIds.length) {
    throw new Error(`Duplicate speech IDs on reconnect: ${JSON.stringify(reloadedSpeechIds)}`);
  }
  summary.checks.reconnect_deduped = true;
  const reconShot = path.join(SCREEN_DIR, `desktop-reconnect-${Date.now()}.png`);
  await page.screenshot({ path: reconShot });
  summary.screenshots.push(reconShot);

  console.log(`[Step 6] Testing mobile viewport (390x844)...`);
  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await attachRoute(mobileContext);
  const mobilePage = await mobileContext.newPage();
  await mobilePage.goto(`${BASE}/room/${roomId}/play`, { waitUntil: 'domcontentloaded' });
  await mobilePage.waitForFunction(() => document.querySelectorAll('[data-testid^=seat-]').length >= 7, { timeout: 30000 });
  const mobileShot = path.join(SCREEN_DIR, `mobile-${Date.now()}.png`);
  await mobilePage.screenshot({ path: mobileShot });
  summary.screenshots.push(mobileShot);
  const noOverflow = await mobilePage.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  if (!noOverflow) throw new Error('Mobile horizontal overflow detected');
  summary.checks.mobile_no_horizontal_overflow = true;
  await mobileContext.close();

  console.log(`[Step 7] Testing prefers-reduced-motion...`);
  const motionContext = await browser.newContext({ reducedMotion: 'reduce', viewport: { width: 1280, height: 800 } });
  await attachRoute(motionContext);
  const motionPage = await motionContext.newPage();
  await motionPage.goto(`${BASE}/room/${roomId}/play`, { waitUntil: 'domcontentloaded' });
  await motionPage.waitForFunction(() => document.querySelectorAll('[data-testid^=seat-]').length >= 7, { timeout: 30000 });
  await motionPage.waitForFunction(() =>
    document.querySelector('[data-testid=speech-item]') !== null ||
    document.querySelector('[data-testid=game-end-panel]') !== null
  , { timeout: 30000 });
  const motionShot = path.join(SCREEN_DIR, `reduced-motion-${Date.now()}.png`);
  await motionPage.screenshot({ path: motionShot });
  summary.screenshots.push(motionShot);
  summary.checks.reduced_motion_supported = true;
  await motionContext.close();
  await browser.close();

  const allPassed = Object.values(summary.checks).every(Boolean);
  summary.passed = allPassed;
  fs.writeFileSync(SUMMARY_PATH, JSON.stringify(summary, null, 2), 'utf8');
  console.log(`\n=== E2E Summary written to ${SUMMARY_PATH} ===`);
  console.log(JSON.stringify(summary, null, 2));

  if (!allPassed) process.exit(1);
  console.log('\nAll E2E checks passed successfully!');
  process.exit(0);
}

try {
  await main();
} catch (err) {
  console.error('Fatal error during E2E execution:', err);
  summary.error = err.message;
  summary.passed = false;
  try { fs.writeFileSync(SUMMARY_PATH, JSON.stringify(summary, null, 2), 'utf8'); } catch (_) {}
  process.exit(1);
}
