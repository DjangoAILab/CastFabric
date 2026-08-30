const { chromium } = require('playwright');
const path = require('path');

const base = 'http://127.0.0.1:4173/docs/prototypes/castfabric-console-v6.html';
const shotDir = process.argv[2] || '/tmp';

function assert(value, message) {
  if (!value) throw new Error(message);
}

async function visibleChinese(page) {
  return page.locator('body').evaluate(root => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const matches = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement && node.parentElement.getClientRects().length && /[\u3400-\u9fff]/.test(node.nodeValue)) {
        matches.push(node.nodeValue.trim());
      }
    }
    return matches.filter(Boolean);
  });
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
  const errors = [];
  page.on('pageerror', error => errors.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });

  await page.goto(base, { waitUntil: 'networkidle' });
  assert(await page.locator('#page-home.active').count() === 1, 'Home is not active');
  const homeSize = await page.evaluate(() => ({
    viewport: innerHeight,
    document: document.documentElement.scrollHeight,
    body: document.body.scrollHeight,
    routes: document.querySelectorAll('#page-home .route-row').length,
  }));
  assert(homeSize.document <= homeSize.viewport, `Desktop Home scrolls: ${JSON.stringify(homeSize)}`);
  assert(homeSize.routes === 3, `Expected 3 Home routes, got ${homeSize.routes}`);
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-home.png'), fullPage: true });

  await page.locator('[data-page-target="speakers"]').first().click();
  assert(await page.locator('#page-speakers.active').count() === 1, 'Speakers page is not active');
  assert(await page.locator('#page-speakers .speaker-row').count() === 7, 'Speakers registry must show 7 independent rows');
  const toggles = page.locator('#page-speakers .speaker-row .suite-toggle');
  const beforeFirst = await toggles.nth(0).getAttribute('aria-pressed');
  const beforeSecond = await toggles.nth(1).getAttribute('aria-pressed');
  await toggles.nth(1).click();
  assert(await toggles.nth(0).getAttribute('aria-pressed') === beforeFirst, 'Toggling one speaker changed another');
  assert(await toggles.nth(1).getAttribute('aria-pressed') !== beforeSecond, 'Speaker toggle did not change');
  await toggles.nth(1).click();
  assert(await toggles.nth(1).getAttribute('aria-pressed') === beforeSecond, 'Speaker toggle did not restore');
  await page.locator('#page-speakers .speaker-row').first().click();
  assert(await page.locator('#speakerOverlay.open').count() === 1, 'Speaker drawer did not open');
  await page.keyboard.press('Escape');
  assert(await page.locator('#speakerOverlay.open').count() === 0, 'Escape did not close speaker drawer');
  await page.waitForTimeout(2300);
  await page.evaluate(() => document.activeElement?.blur());
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-speakers.png'), fullPage: true });

  await page.locator('[data-page-target="activity"]').first().click();
  assert(await page.locator('#page-activity.active').count() === 1, 'Activity page is not active');
  assert(await page.locator('.event-item').count() === 6, 'Expected 6 structured events');
  await page.locator('#resultFilter').selectOption('failed');
  assert(await page.locator('.event-item:visible').count() === 2, 'Outcome filter did not isolate 2 issue events');
  await page.locator('.event-item:visible').first().click();
  assert(await page.locator('#eventOverlay.open').count() === 1, 'Event detail drawer did not open');
  await page.keyboard.press('Escape');
  await page.locator('#resultFilter').selectOption('all');
  await page.evaluate(() => document.activeElement?.blur());
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-activity.png'), fullPage: true });

  await page.locator('[data-open-settings]').first().click();
  for (const section of ['discovery', 'identity', 'playback', 'network', 'extensions', 'system']) {
    await page.locator(`[data-settings-section="${section}"]`).click();
    assert(await page.locator(`[data-section-panel="${section}"].active`).count() === 1, `Settings section ${section} did not activate`);
  }
  await page.locator('[data-field="system.language"]').selectOption({ label: 'English' });
  assert(await page.locator('html').getAttribute('lang') === 'en', 'English mode did not activate');
  for (const section of ['discovery', 'identity', 'playback', 'network', 'extensions', 'system']) {
    await page.locator(`[data-settings-section="${section}"]`).click();
    const mixed = await visibleChinese(page);
    assert(mixed.length === 0, `English settings/${section} contain Chinese: ${mixed.join(' | ')}`);
  }
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-connections-en.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await page.locator('body').click({ position: { x: 5, y: 5 } });

  for (const section of ['home', 'speakers', 'activity']) {
    await page.locator(`[data-page-target="${section}"]`).first().click();
    const mixed = await visibleChinese(page);
    assert(mixed.length === 0, `English page/${section} contains Chinese: ${mixed.join(' | ')}`);
  }

  await page.locator('#languageButton').click();
  await page.locator('[data-page-target="speakers"]').first().click();
  await page.locator('#reviewToggle').click();
  for (const scenario of ['empty', 'loading', 'degraded', 'error', 'normal']) {
    await page.locator('#scenarioSelect').selectOption(scenario);
    assert(await page.locator('body').getAttribute('data-scenario') === scenario, `Scenario ${scenario} did not apply`);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('[data-page-target="speakers"]').first().click();
  const mobile = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    rows: document.querySelectorAll('#page-speakers .speaker-row').length,
  }));
  assert(mobile.document <= mobile.viewport, `Mobile has horizontal overflow: ${JSON.stringify(mobile)}`);
  assert(mobile.rows === 7, 'Mobile lost speaker rows');
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-speakers-mobile.png'), fullPage: true });
  await page.locator('[data-page-target="activity"]').first().click();
  assert(await page.locator('.event-item').count() === 6, 'Mobile lost activity events');
  await page.screenshot({ path: path.join(shotDir, 'castfabric-console-v6-activity-mobile.png'), fullPage: true });

  assert(errors.length === 0, errors.join('\n'));
  await browser.close();
  console.log('PASS: desktop, mobile, i18n, overlays, filters, independent toggles, and review states');
})().catch(async error => {
  console.error(error.stack || error);
  process.exit(1);
});
