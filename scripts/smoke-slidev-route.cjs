#!/usr/bin/env node
/*
 * Focused routed-browser smoke test for the sandboxed Slidev iframe.
 * Usage (with a real build made using Slidev's base: ./ headmatter):
 *   cd backend/nodejs/apps
 *   SLIDEV_DIST=/path/to/dist TS_NODE_PROJECT=tsconfig.test.json \
 *     node -r ts-node/register ../../../scripts/smoke-slidev-route.cjs
 * Requires Playwright from frontend dependencies and a local Chrome/Chromium.
 * The Node route is real; its internal Python-content fetch is mocked from dist.
 */
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const root = path.resolve(__dirname, "..");
const appRequire = createRequire(
  path.join(root, "backend/nodejs/apps/package.json"),
);
const frontendRequire = createRequire(path.join(root, "frontend/package.json"));
const express = appRequire("express");
const jwt = appRequire("jsonwebtoken");
const sinon = appRequire("sinon");
const { chromium } = frontendRequire("playwright");
const { createDeckPreviewRouter } = appRequire(
  path.join(
    root,
    "backend/nodejs/apps/src/modules/artifacts/routes/deck-preview.routes.ts",
  ),
);
const owner = appRequire(
  path.join(
    root,
    "backend/nodejs/apps/src/modules/artifacts/services/share-owner.ts",
  ),
);
const shareResolver = appRequire(
  path.join(
    root,
    "backend/nodejs/apps/src/modules/artifacts/services/resolve-share.ts",
  ),
);

const dist = process.env.SLIDEV_DIST && path.resolve(process.env.SLIDEV_DIST);
if (!dist || !fs.statSync(dist, { throwIfNoEntry: false })?.isDirectory()) {
  throw new Error("Set SLIDEV_DIST to a built Slidev dist/ directory.");
}
const secret = "local-slidev-route-smoke-secret";
const artifactId = "browser-smoke-artifact";
const version = 2;
const capability = jwt.sign(
  {
    purpose: "deck-preview",
    artifactId,
    version,
    userId: "507f1f77bcf86cd799439011",
    orgId: "507f1f77bcf86cd799439012",
    name: "slidev-presentation.zip",
    mimeType: "application/zip",
  },
  secret,
  { algorithm: "HS256" },
);
const assetRequests = [];
const verifiedServiceScopes = [];
const shareToken = "local-smoke-share-token";
const shareAuthority = {
  artifactId,
  version,
  contentHash: "a".repeat(64),
  name: "slidev-presentation.zip",
  mimeType: "application/zip",
  orgId: "507f1f77bcf86cd799439012",
  ownerId: "507f1f77bcf86cd799439011",
};
const originalFetch = global.fetch;
sinon.stub(owner, "isShareOwnerActive").resolves(true);
sinon
  .stub(shareResolver, "resolveShare")
  .callsFake(async (candidate, authorize) => {
    if (candidate !== shareToken || !(await authorize(shareAuthority)))
      return null;
    return shareAuthority;
  });
global.fetch = async (input, init) => {
  const url = new URL(
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url,
  );
  if (url.hostname !== "connector.local") return originalFetch(input, init);
  const sharedRequest = url.pathname.endsWith("/artifact-share/content");
  const serviceClaims = jwt.verify(
    new Headers(init?.headers).get("authorization").slice("Bearer ".length),
    secret,
  );
  const requiredScope = sharedRequest
    ? "artifact-share:content"
    : "artifact-deck:content";
  if (!serviceClaims.scopes?.includes(requiredScope)) {
    return new Response("invalid scoped service token", { status: 401 });
  }
  verifiedServiceScopes.push(requiredScope);
  const relativePath =
    url.searchParams.get(sharedRequest ? "deck_path" : "path") || "index.html";
  assetRequests.push(relativePath);
  const target = path.resolve(dist, relativePath);
  if (!target.startsWith(`${dist}${path.sep}`) || !fs.existsSync(target)) {
    return new Response("Presentation unavailable", { status: 404 });
  }
  let content = fs.readFileSync(target);
  if (relativePath === "index.html") {
    const storageShim = `<script>(function(){for(const key of ['localStorage','sessionStorage']){const values=new Map();const store={getItem:k=>values.has(String(k))?values.get(String(k)):null,setItem:(k,v)=>values.set(String(k),String(v)),removeItem:k=>values.delete(String(k)),clear:()=>values.clear(),key:i=>Array.from(values.keys())[i]??null,get length(){return values.size}};Object.defineProperty(window,key,{value:store,configurable:true});}})();</script>`;
    content = Buffer.from(
      content.toString().replace(/(<head\b[^>]*>)/i, `$1${storageShim}`),
    );
  }
  const extension = path.extname(relativePath).toLowerCase();
  const contentType =
    {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".mjs": "text/javascript; charset=utf-8",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".woff2": "font/woff2",
      ".woff": "font/woff",
      ".otf": "font/otf",
      ".ttf": "font/ttf",
    }[extension] || "application/octet-stream";
  return new Response(content, { headers: { "content-type": contentType } });
};

(async () => {
  const app = express();
  app.get("/viewer/:mode", (req, res) => {
    const deckPath =
      req.params.mode === "shared"
        ? `/decks/shared/${shareToken}/index.html`
        : `/decks/${artifactId}/${version}/${capability}/index.html`;
    res
      .type("html")
      .send(
        `<html><body><iframe id="deck" title="Deck" sandbox="allow-scripts" ` +
          `src="${deckPath}" style="width:960px;height:540px"></iframe></body></html>`,
      );
  });
  app.use(
    "/decks",
    createDeckPreviewRouter({
      connectorBackend: "http://connector.local",
      scopedJwtSecret: secret,
    }),
  );
  const server = app.listen(0, "127.0.0.1");
  const launchOptions = {
    headless: true,
    ...(process.env.CHROME_BIN
      ? { executablePath: process.env.CHROME_BIN }
      : {}),
    args: ["--no-sandbox"],
  };
  let browser;
  try {
    browser = await chromium.launch(launchOptions);
    const { port } = server.address();
    const page = await browser.newPage();
    const browserErrors = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    const results = [];
    for (const mode of ["private", "shared"]) {
      await page.goto(`http://127.0.0.1:${port}/viewer/${mode}`);
      const deck = page.frameLocator("#deck");
      await deck.locator("body").waitFor({ state: "visible" });
      await page.waitForTimeout(2500);
      const firstSlide = await deck.locator("body").innerText();
      if (!firstSlide.trim())
        throw new Error(`${mode} Slidev rendered an empty deck.`);
      await deck.getByRole("button", { name: "Go to next slide" }).click();
      await page.waitForTimeout(700);
      const secondSlide = await deck.locator("body").innerText();
      if (secondSlide === firstSlide)
        throw new Error(`${mode} slide navigation did not change the page.`);
      results.push({ mode, navigationChangedSlide: true });
    }
    if (!assetRequests.some((name) => name !== "index.html")) {
      throw new Error("No built asset was requested through /decks/.");
    }
    if (
      !verifiedServiceScopes.includes("artifact-deck:content") ||
      !verifiedServiceScopes.includes("artifact-share:content")
    ) {
      throw new Error(
        `private/shared route did not issue separate scoped service tokens: ${verifiedServiceScopes.join(",")}`,
      );
    }
    const unexpectedErrors = browserErrors.filter(
      (message) =>
        !message.includes("WakeLock") && !message.includes("Screen Wake Lock"),
    );
    if (unexpectedErrors.length) {
      throw new Error(
        `Unexpected browser errors: ${unexpectedErrors.join("; ")}`,
      );
    }
    console.log(
      JSON.stringify(
        {
          result: "passed",
          previews: results,
          routedAssets: assetRequests,
          serviceScopes: [...new Set(verifiedServiceScopes)],
          nonfatalSandboxWarnings: browserErrors,
        },
        null,
        2,
      ),
    );
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
    global.fetch = originalFetch;
    sinon.restore();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
