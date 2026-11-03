import { expect } from 'chai';
import express from 'express';
import { AddressInfo } from 'net';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'fs';
import os from 'os';
import path from 'path';
import {
  suppressShareBodyParserError,
  isShareTokenRequest,
  isShareViewerRequest,
  sendShareViewerShell,
} from '../../../src/modules/artifacts/services/share-request-privacy';
import { ErrorMiddleware } from '../../../src/libs/middlewares/error.middleware';

describe('share bearer request privacy', () => {
  it('recognizes only token endpoints', () => {
    expect(isShareTokenRequest('/api/v1/artifact-shares/content')).to.equal(
      true,
    );
    expect(isShareTokenRequest('/api/v1/artifact-shares/metadata')).to.equal(
      true,
    );
    expect(isShareTokenRequest('/API/V1/ARTIFACT-SHARES/CONTENT/')).to.equal(
      true,
    );
    expect(isShareTokenRequest('/api/v1/artifact-shares/unknown')).to.equal(
      true,
    );
    expect(isShareTokenRequest('/api/v1/artifacts')).to.equal(false);
    expect(
      isShareTokenRequest('/decks/artifact-1/3/private-cap/index.html'),
    ).to.equal(true);
    expect(
      isShareTokenRequest('/decks/shared/share-secret/assets/theme.css'),
    ).to.equal(true);
  });

  it('recognizes the static share viewer and hides query credentials from error logs', () => {
    expect(isShareViewerRequest('/share/')).to.equal(true);
    expect(isShareViewerRequest('/share')).to.equal(true);
    expect(isShareViewerRequest('/share/other')).to.equal(true);
    expect(isShareViewerRequest('/share/other/nested')).to.equal(false);
    const context = (ErrorMiddleware as any).getRequestContext({
      method: 'GET',
      path: '/share/',
      query: { token: 'private-token' },
      params: {},
      headers: { referer: 'https://example.com/share/?token=private-token' },
    });
    expect(JSON.stringify(context)).not.to.include('private-token');
    const pathContext = (ErrorMiddleware as any).getRequestContext({
      method: 'GET',
      path: '/share/private-token',
      query: {},
      params: { token: 'private-token' },
      headers: { referer: 'https://example.com/share/private-token' },
    });
    expect(JSON.stringify(pathContext)).not.to.include('private-token');
    const deckContext = (ErrorMiddleware as any).getRequestContext({
      method: 'GET',
      path: '/decks/artifact-1/3/private-cap/index.html',
      query: { token: 'private-cap' },
      params: { capability: 'private-cap' },
      headers: {
        referer:
          'https://example.com/decks/artifact-1/3/private-cap/index.html',
      },
    });
    expect(JSON.stringify(deckContext)).not.to.include('private-cap');
    expect(deckContext.path).to.equal(
      '/decks/artifact-1/3/[REDACTED]/index.html',
    );
  });

  it('serves the share shell at a token path without a redirect or caching', async () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'share-viewer-'));
    mkdirSync(path.join(dir, 'share'));
    writeFileSync(
      path.join(dir, 'share', 'index.html'),
      '<html>share shell</html>',
    );
    const app = express();
    app.get('*', (req, res) => {
      if (!sendShareViewerShell(req, res, dir)) res.sendStatus(404);
    });
    const server = app.listen(0);
    try {
      const port = (server.address() as AddressInfo).port;
      const response = await fetch(
        `http://127.0.0.1:${port}/share/${'A'.repeat(43)}`,
        { redirect: 'manual' },
      );
      expect(response.status).to.equal(200);
      expect(response.headers.get('location')).to.equal(null);
      expect(response.headers.get('cache-control')).to.include('no-store');
      expect(response.headers.get('referrer-policy')).to.equal('no-referrer');
      expect(await response.text()).to.include('share shell');
    } finally {
      server.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('suppresses malformed JSON body errors on token endpoints', async () => {
    const app = express();
    let forwarded = false;
    app.use(express.json());
    app.use(suppressShareBodyParserError);
    app.use(
      (
        error: unknown,
        _req: express.Request,
        res: express.Response,
        _next: express.NextFunction,
      ) => {
        forwarded = true;
        res.status(500).send(String(error));
      },
    );
    const server = app.listen(0);
    try {
      const port = (server.address() as AddressInfo).port;
      const response = await fetch(
        `http://127.0.0.1:${port}/api/v1/artifact-shares/content`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: '{"token":"sensitive-secret"',
        },
      );
      expect(response.status).to.equal(404);
      expect(await response.text()).not.to.include('sensitive-secret');
      expect(response.headers.get('cache-control')).to.include('no-store');
      expect(forwarded).to.equal(false);
    } finally {
      server.close();
    }
  });
});
