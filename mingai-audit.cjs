const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().substring(0, 200)); });
  page.on('pageerror', err => { errors.push('PAGE_ERROR: ' + err.message.substring(0, 200)); });

  // 1. Login
  console.log('=== LOGIN ===');
  await page.goto('http://localhost:3022/login', { waitUntil: 'networkidle', timeout: 15000 });
  await page.fill('input[type="email"]', 'admin@mingai.test');
  await page.fill('input[type="password"]', 'Admin1234!');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(3000);
  console.log('After login: ' + page.url());
  await page.screenshot({ path: '/tmp/mingai-01-after-login.png' });

  // Get page text
  const bodyText = await page.textContent('body');
  console.log('Body (800): ' + bodyText.substring(0, 800).replace(/\s+/g, ' '));

  // Check all nav links
  const navLinks = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a[href]')).map(l => ({
      href: l.getAttribute('href'),
      text: l.textContent.trim().substring(0, 50)
    })).filter(l => l.href && l.href.startsWith('/'));
  });
  console.log('\nNav links: ' + JSON.stringify(navLinks, null, 2));

  // 2. Try each page
  const pages = [
    '/dashboard', '/tenants', '/llm-profiles', '/issue-queue',
    '/cost-analytics', '/settings', '/chat', '/glossary',
    '/documents', '/users', '/agents', '/analytics',
    '/settings/issue-queue'
  ];

  for (const p of pages) {
    console.log('\n=== ' + p + ' ===');
    try {
      await page.goto('http://localhost:3022' + p, { waitUntil: 'networkidle', timeout: 10000 });
      await page.waitForTimeout(1000);
      const url = page.url();
      const text = (await page.textContent('body')).substring(0, 400).replace(/\s+/g, ' ');
      const is404 = text.includes('404') || text.includes('not be found');
      const isRedirected = !url.includes(p);
      console.log('URL: ' + url + (isRedirected ? ' (REDIRECTED)' : '') + (is404 ? ' (404)' : ''));
      console.log('Content: ' + text.substring(0, 300));
      const fname = p.replace(/\//g, '-').replace(/^-/, '');
      await page.screenshot({ path: '/tmp/mingai-' + fname + '.png' });
    } catch(e) {
      console.log('ERROR: ' + e.message.substring(0, 200));
    }
  }

  console.log('\n=== CONSOLE ERRORS ===');
  errors.forEach(e => console.log('  ' + e));

  await browser.close();
})();
