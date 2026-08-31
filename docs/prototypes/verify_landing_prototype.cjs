const { chromium } = require('playwright');

const baseUrl = process.env.CASTFABRIC_LANDING_URL ||
  'http://127.0.0.1:4173/docs/prototypes/castfabric-landing-v1.html';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  const page = await context.newPage();
  const errors = [];
  page.on('console', message => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('pageerror', error => errors.push(`page: ${error.message}`));

  await page.addInitScript(() => localStorage.removeItem('castfabric-landing-language-v1'));
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await page.locator('img').evaluateAll(images => Promise.all(images.map(image => {
    if (image.complete) return;
    return new Promise(resolve => image.addEventListener('load', resolve, { once: true }));
  })));

  assert(await page.locator('h1').innerText() === '不挑协议，\n投了就播。', 'Chinese slogan is missing or changed');
  assert(await page.locator('.route-row').count() === 3, 'Expected three protocol routes');
  assert(await page.locator('.route-row .output-endpoint').count() === 3, 'Each route needs an output speaker');
  assert(await page.locator('.console-frame img').evaluate(image => image.naturalWidth > 0), 'Desktop product image failed to load');
  assert(await page.locator('.mobile-proof img').evaluate(image => image.naturalWidth > 0), 'Mobile product image failed to load');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'Desktop has horizontal overflow');
  assert(await page.locator('.hero').evaluate(element => element.getBoundingClientRect().height <= 900), 'Desktop hero does not fit in one viewport');

  await page.screenshot({ path: '/tmp/castfabric-landing-v1-desktop.png', fullPage: false });
  await page.locator('.product-grid').screenshot({ path: '/tmp/castfabric-landing-v1-product.png' });

  await page.locator('#languageButton').click();
  assert(await page.getAttribute('html', 'lang') === 'en', 'Language switch did not update the document language');
  assert(await page.locator('h1').innerText() === 'Cast freely.\nIt just plays.', 'English slogan is missing or changed');
  const visibleChinese = await page.evaluate(() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const values = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!parent || ['SCRIPT', 'STYLE'].includes(parent.tagName)) continue;
      if (getComputedStyle(parent).display === 'none') continue;
      if (/[\u3400-\u9fff]/.test(node.textContent)) values.push(node.textContent.trim());
    }
    return values.filter(Boolean);
  });
  assert(visibleChinese.length === 0, `English mode still contains Chinese: ${visibleChinese.join(' | ')}`);
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: '/tmp/castfabric-landing-v1-desktop-en.png', fullPage: false });

  const heroCopy = page.locator('.quick-command .copy-button');
  await heroCopy.click();
  await page.waitForFunction(() => document.querySelector('.quick-command .copy-button')?.dataset.state);
  assert(await heroCopy.getAttribute('data-state') === 'copied', 'Copy action did not report success');

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload({ waitUntil: 'networkidle' });
  assert(await page.locator('.signal-pulse').first().evaluate(element => getComputedStyle(element).display === 'none'), 'Reduced motion does not hide the travelling pulse');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => localStorage.setItem('castfabric-landing-language-v1', 'zh'));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.reload({ waitUntil: 'networkidle' });
  await page.evaluate(() => scrollTo(0, 0));
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'Mobile has horizontal overflow');
  assert(await page.locator('.route-row').count() === 3, 'Mobile lost protocol routes');
  await page.screenshot({ path: '/tmp/castfabric-landing-v1-mobile.png', fullPage: false });
  await page.locator('.deploy-card').screenshot({ path: '/tmp/castfabric-landing-v1-mobile-deploy.png' });

  assert(errors.length === 0, errors.join('\n'));
  console.log('PASS: landing prototype desktop/mobile, bilingual copy, images, copy action and reduced motion');
  await browser.close();
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
