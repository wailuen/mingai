const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().substring(0, 300)); });

  // Login
  await page.goto('http://localhost:3022/login', { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('input[type="email"]', 'admin@mingai.test');
  await page.fill('input[type="password"]', 'Admin1234!');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  console.log('Logged in at: ' + page.url());

  // Now test all real routes under /settings
  const settingsPages = [
    '/settings/dashboard',
    '/settings/tenants',
    '/settings/issue-queue',
    '/settings/llm-profiles',
    '/settings/agent-templates',
    '/settings/analytics-platform',
    '/settings/tool-catalog',
    '/settings/cost-analytics',
    '/settings/users',
    '/settings/knowledge-base',
    '/settings/agents',
    '/settings/glossary',
  ];

  for (const p of settingsPages) {
    console.log('\n=== ' + p + ' ===');
    try {
      await page.goto('http://localhost:3022' + p, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(2000);
      const url = page.url();

      // Get visible text content (skip script tags)
      const visibleText = await page.evaluate(() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let text = '';
        while (walker.nextNode()) {
          const parent = walker.currentNode.parentElement;
          if (parent && !['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName)) {
            const t = walker.currentNode.textContent.trim();
            if (t) text += t + ' ';
          }
        }
        return text.substring(0, 1500);
      });

      const is404 = visibleText.includes('404') && visibleText.includes('could not be found');
      console.log('URL: ' + url + (is404 ? ' [404]' : ' [OK]'));
      console.log('Visible text: ' + visibleText.substring(0, 600));

      // Check key UI elements
      const stats = {
        tables: await page.locator('table').count(),
        buttons: await page.locator('button').count(),
        cards: await page.locator('[class*="card"], [class*="Card"]').count(),
        headings: await page.locator('h1, h2, h3').count(),
        inputs: await page.locator('input, select, textarea').count(),
      };
      console.log('UI elements: ' + JSON.stringify(stats));

      const fname = p.replace(/\//g, '-').replace(/^-/, '');
      await page.screenshot({ path: '/tmp/' + fname + '.png' });

    } catch(e) {
      console.log('ERROR: ' + e.message.substring(0, 300));
    }
  }

  // Also test the chat page
  console.log('\n=== /chat ===');
  try {
    await page.goto('http://localhost:3022/chat', { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForTimeout(3000);
    const chatText = await page.evaluate(() => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let text = '';
      while (walker.nextNode()) {
        const parent = walker.currentNode.parentElement;
        if (parent && !['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName)) {
          const t = walker.currentNode.textContent.trim();
          if (t) text += t + ' ';
        }
      }
      return text.substring(0, 1000);
    });
    console.log('URL: ' + page.url());
    console.log('Visible: ' + chatText.substring(0, 600));
    await page.screenshot({ path: '/tmp/chat.png' });
  } catch(e) {
    console.log('CHAT ERROR: ' + e.message.substring(0, 200));
  }

  console.log('\n=== CONSOLE ERRORS (unique) ===');
  const unique = [...new Set(errors)];
  unique.forEach(e => console.log('  ' + e));

  await browser.close();
})();
