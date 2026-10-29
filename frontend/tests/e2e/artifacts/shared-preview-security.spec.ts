import { expect, test } from '@playwright/test';

function minimalPdf(): Buffer {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>',
    '<< /Length 15 >>\nstream\n0 0 100 100 re f\nendstream',
  ];
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((body, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${body}\nendobj\n`; });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${offsets.length}\n0000000000 65535 f \n`;
  offsets.slice(1).forEach((offset) => { pdf += `${String(offset).padStart(10, '0')} 00000 n \n`; });
  pdf += `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

test('shared PDF renders a page without fetching a third-party worker', async ({ page }) => {
  const thirdParty: string[] = [];
  page.on('request', (request) => { if (request.url().includes('unpkg.com')) thirdParty.push(request.url()); });
  await page.route('**/api/v1/artifact-shares/metadata', (route) => route.fulfill({ json: { version: 1, name: 'test.pdf', mimeType: 'application/pdf' } }));
  await page.route('**/api/v1/artifact-shares/content', (route) => route.fulfill({ status: 200, contentType: 'application/octet-stream', body: minimalPdf() }));
  await page.goto(`/share/#${'A'.repeat(43)}`);
  await expect(page.getByLabel('PDF page 1')).toBeVisible();
  await expect(page.getByText('Page 1 of 1')).toBeVisible();
  expect(thirdParty).toEqual([]);
});

for (const kind of ['html', 'svg'] as const) {
  test(`shared ${kind} preview renders with its sandbox and CSP`, async ({ page }) => {
    const blockedRequests: string[] = [];
    await page.route('**/private-network-probe', (route) => {
      blockedRequests.push(route.request().url());
      return route.fulfill({ status: 200, body: 'private' });
    });
    await page.route('**/api/v1/artifact-shares/metadata', (route) => route.fulfill({
      json: { version: 1, name: `test.${kind}`, mimeType: kind === 'html' ? 'text/html' : 'image/svg+xml' },
    }));
    const payload = kind === 'html'
      ? '<!doctype html><html><head><style>body.report { background: rgb(1, 2, 3) } p { color: rgb(255, 0, 0); background-image: url(/private-network-probe) }</style></head><body class="report"><script>document.body.dataset.ready="yes";try { parent.document.body.dataset.compromised="yes" } catch(e) {} fetch("/private-network-probe").catch(() => {})</script><img src="/private-network-probe"><p>Shared artifact text</p></body></html>'
      : '<svg xmlns="http://www.w3.org/2000/svg"><script>parent.document.body.dataset.compromised="yes";fetch("/private-network-probe")</script><image href="/private-network-probe"/><text x="1" y="20">Shared artifact text</text></svg>';
    await page.route('**/api/v1/artifact-shares/content', (route) => route.fulfill({ status: 200, contentType: 'application/octet-stream', body: payload }));
    await page.goto(`/share/#${'A'.repeat(43)}`);
    if (kind === 'html') {
      const frame = page.frameLocator('iframe[title="Preview of test.html"]');
      await expect(frame.getByText('Shared artifact text')).toBeVisible();
      await expect(frame.getByText('Shared artifact text')).toHaveCSS('color', 'rgb(255, 0, 0)');
      await expect(frame.locator('body')).toHaveCSS('background-color', 'rgb(1, 2, 3)');
      await expect(frame.locator('body')).toHaveAttribute('data-ready', 'yes');
      await expect(page.locator('iframe[title="Preview of test.html"]')).toHaveAttribute('sandbox', 'allow-scripts');
    } else {
      const image = page.getByRole('img', { name: 'test.svg' });
      await expect(image).toBeVisible();
      await expect.poll(() => image.evaluate((node) => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
    }
    await page.waitForTimeout(500);
    expect(await page.locator('body').getAttribute('data-compromised')).toBeNull();
    expect(blockedRequests).toEqual([]);
    await page.getByRole('button', { name: 'Full screen' }).click();
    await expect(page.getByRole('button', { name: 'Exit full screen' })).toBeVisible();
    await page.getByRole('button', { name: 'Exit full screen' }).click();
    await expect(page.getByRole('button', { name: 'Full screen' })).toBeVisible();
  });
}
