const { chromium } = require('playwright');
const path = require('path');
const base = 'http://127.0.0.1:4173/docs/prototypes/castfabric-server-playlists-review.html';
const shotDir = process.argv[2] || '/tmp';
const assert = (value, message) => { if (!value) throw new Error(message); };

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 860 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base, { waitUntil: 'networkidle' });
  assert(await page.locator('#overview.active').count(), 'overview did not load');
  await page.screenshot({ path: path.join(shotDir, 'server-playlists-overview-zh.png'), fullPage: true });
  await page.locator('[data-page="playlists"]').click();
  assert(await page.locator('#playlists.active').count(), 'playlists did not open');
  await page.locator('[data-open-playlist]').first().click();
  assert(await page.locator('#playlistDrawer.open').count(), 'playlist detail did not open');
  await page.locator('[data-open-conflict]').click();
  assert(await page.locator('#conflict.open').count(), 'active-item conflict did not open');
  await page.keyboard.press('Escape');
  await page.locator('[data-open-assets]').first().click();
  assert(await page.locator('#assetsDrawer.open').count(), 'asset management did not open');
  await page.keyboard.press('Escape');
  await page.locator('#language').click();
  assert(await page.locator('html').getAttribute('lang') === 'en', 'English mode did not activate');
  const mixed = await page.locator('body').evaluate(root => /[\u3400-\u9fff]/.test(root.innerText.replace('中', '')));
  assert(!mixed, 'English UI contains Chinese copy');
  await page.screenshot({ path: path.join(shotDir, 'server-playlists-en.png'), fullPage: true });
  for (const state of ['normal', 'empty', 'loading', 'degraded', 'error']) {
    await page.locator('#scenario').selectOption(state);
    assert(await page.locator('body').getAttribute('data-scenario') === state, `review state ${state} did not apply`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#scenario').selectOption('normal');
  await page.locator('[data-page="playlists"]').click();
  const width = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert(width.scroll <= width.viewport, `mobile overflow: ${JSON.stringify(width)}`);
  await page.screenshot({ path: path.join(shotDir, 'server-playlists-mobile-en.png'), fullPage: true });
  assert(!errors.length, errors.join('\n'));
  await browser.close();
  console.log('PASS: playlist review prototype desktop/mobile, bilingual, drawers, conflict, and review states');
})().catch(error => { console.error(error.stack || error); process.exit(1); });
