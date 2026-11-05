import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

// Radix creates a fresh jade theme inside its dialog portal. Test the actual
// CSS in a browser: jsdom does not resolve the custom color variables.
test('the share dialog and expiration menu stack above fullscreen preview', async ({ page }) => {
  await page.setContent(`<html><body>
    <div id="preview" style="position:fixed;inset:0;z-index:100"></div>
    <div class="rt-DialogOverlay" style="position:fixed;inset:0">
      <div class="artifact-share-dialog" style="position:absolute;left:100px;top:100px;width:200px;height:200px"></div>
    </div>
    <div data-radix-popper-content-wrapper style="position:fixed;left:120px;top:120px;z-index:auto">
      <div class="artifact-share-expiration-select" style="width:100px;height:100px"></div>
    </div>
  </body></html>`);
  await page.addStyleTag({ content: readFileSync('app/globals.css', 'utf8').replace(/^@import .*;$/gm, '') });
  expect(await page.evaluate(() => document.elementFromPoint(105, 105)?.className)).toBe('artifact-share-dialog');
  expect(await page.evaluate(() => document.elementFromPoint(125, 125)?.className)).toBe('artifact-share-expiration-select');
});

for (const appearance of ['light', 'dark']) {
  test(`portaled and explicit jade action buttons use the brand palette in ${appearance} mode`, async ({ page }) => {
    await page.setContent(`<html class="${appearance}"><body>
      <div class="radix-themes" data-accent-color="jade">
        <button class="rt-BaseButton rt-Button rt-variant-solid" id="primary">Create link</button>
        <button class="rt-BaseButton rt-Button rt-variant-soft" id="secondary">Close</button>
        <button class="rt-BaseButton rt-Button rt-variant-solid" data-accent-color="jade" id="legacy">Save</button>
        <button class="rt-BaseButton rt-Button rt-variant-solid" data-accent-color="red" id="danger">Delete</button>
      </div>
    </body></html>`);
    await page.addStyleTag({ content: readFileSync('node_modules/@radix-ui/themes/styles.css', 'utf8') });
    await page.addStyleTag({ content: readFileSync('app/globals.css', 'utf8').replace(/^@import .*;$/gm, '') });
    await expect(page.locator('#primary')).toHaveCSS('background-color', 'rgb(253, 83, 60)');
    await expect(page.locator('#secondary')).toHaveCSS('background-color', 'rgba(253, 83, 60, 0.12)');
    await expect(page.locator('#legacy')).toHaveCSS('background-color', 'rgb(253, 83, 60)');
    await expect(page.locator('#danger')).not.toHaveCSS('background-color', 'rgb(253, 83, 60)');
  });
}
