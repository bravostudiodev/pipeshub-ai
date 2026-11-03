import { expect } from 'chai';
import express from 'express';
import { AddressInfo } from 'net';
import jwt from 'jsonwebtoken';
import sinon from 'sinon';
import { AppConfig } from '../../../src/modules/tokens_manager/config/config';
import { createDeckPreviewRouter } from '../../../src/modules/artifacts/routes/deck-preview.routes';
import * as resolve from '../../../src/modules/artifacts/services/resolve-share';
import * as client from '../../../src/modules/artifacts/services/share-content-client';
import * as owner from '../../../src/modules/artifacts/services/share-owner';

describe('Slidev deck preview routes', () => {
  afterEach(() => sinon.restore());
  const secret = 'test-preview-secret';
  const config = {
    connectorBackend: 'http://connector',
    scopedJwtSecret: secret,
  } as AppConfig;
  const authority = {
    orgId: 'org',
    ownerId: 'owner',
    artifactId: 'artifact',
    version: 2,
    contentHash: 'a'.repeat(64),
    name: 'slidev-presentation.zip',
    mimeType: 'application/zip',
  };

  async function appRequest(path: string) {
    const app = express();
    app.use('/decks', createDeckPreviewRouter(config));
    const server = app.listen(0);
    try {
      const port = (server.address() as AddressInfo).port;
      return await fetch(`http://127.0.0.1:${port}/decks/${path}`);
    } finally {
      server.close();
    }
  }

  it('serves the exact private version under a sandbox CSP and no-store headers', async () => {
    const capability = jwt.sign(
      {
        purpose: 'deck-preview',
        artifactId: 'artifact',
        version: 2,
        userId: 'user',
        orgId: 'org',
        name: 'slidev-presentation.zip',
        mimeType: 'application/zip',
      },
      secret,
      { algorithm: 'HS256' },
    );
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    const originalFetch = globalThis.fetch;
    let upstreamUrl: URL | undefined;
    let serviceAuthorization = '';
    sinon.stub(globalThis, 'fetch').callsFake(async (input, init) => {
      const url = new URL(
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
      );
      if (url.hostname === 'connector') {
        upstreamUrl = url;
        serviceAuthorization =
          new Headers(init?.headers).get('authorization') || '';
        return new Response('<html>deck</html>', {
          headers: { 'content-type': 'text/html; charset=utf-8' },
        });
      }
      return originalFetch(input, init);
    });
    const response = await appRequest(`artifact/2/${capability}/index.html`);
    expect(response.status).to.equal(200);
    expect(response.headers.get('content-security-policy')).to.equal(
      'sandbox allow-scripts',
    );
    expect(response.headers.get('access-control-allow-origin')).to.equal('*');
    expect(response.headers.get('cache-control')).to.include('no-store');
    expect(await response.text()).to.equal('<html>deck</html>');
    expect(upstreamUrl?.pathname).to.equal(
      '/api/v1/internal/artifact-deck/file',
    );
    expect(upstreamUrl?.searchParams.get('path')).to.equal('index.html');
    const serviceClaims = jwt.verify(
      serviceAuthorization.slice('Bearer '.length),
      secret,
    ) as jwt.JwtPayload;
    expect(serviceClaims).to.include({
      artifactId: 'artifact',
      version: 2,
      userId: 'user',
      orgId: 'org',
    });
    expect(serviceClaims.scopes).to.deep.equal(['artifact-deck:content']);
  });

  it('refuses private previews when the requesting account is no longer active', async () => {
    const capability = jwt.sign(
      {
        purpose: 'deck-preview',
        artifactId: 'artifact',
        version: 2,
        userId: 'user',
        orgId: 'org',
        name: 'slidev-presentation.zip',
        mimeType: 'application/zip',
      },
      secret,
      { algorithm: 'HS256' },
    );
    sinon.stub(owner, 'isShareOwnerActive').resolves(false);
    const originalFetch = globalThis.fetch;
    let contentRequests = 0;
    sinon.stub(globalThis, 'fetch').callsFake(async (input, init) => {
      const url = new URL(
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
      );
      if (url.hostname === 'connector') contentRequests += 1;
      return originalFetch(input, init);
    });
    const response = await appRequest(`artifact/2/${capability}/index.html`);
    expect(response.status).to.equal(404);
    expect(contentRequests).to.equal(0);
  });

  it('refuses a capability for a different artifact before reaching the content service', async () => {
    const capability = jwt.sign(
      {
        purpose: 'deck-preview',
        artifactId: 'other-artifact',
        version: 2,
        userId: 'user',
        orgId: 'org',
        name: 'slidev-presentation.zip',
        mimeType: 'application/zip',
      },
      secret,
      { algorithm: 'HS256' },
    );
    const originalFetch = globalThis.fetch;
    let contentRequests = 0;
    sinon.stub(globalThis, 'fetch').callsFake(async (input, init) => {
      const url = new URL(
        typeof input === 'string'
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
      );
      if (url.hostname === 'connector') {
        contentRequests += 1;
        return new Response('unexpected');
      }
      return originalFetch(input, init);
    });
    const response = await appRequest(`artifact/2/${capability}/index.html`);
    expect(response.status).to.equal(404);
    expect(contentRequests).to.equal(0);
  });

  it('serves shared deck assets only after resolving the current pinned share', async () => {
    const resolveStub = sinon
      .stub(resolve, 'resolveShare')
      .callsFake(async (token, authorize) => {
        expect(token).to.equal('share-token');
        expect(await authorize(authority)).to.equal(true);
        return authority;
      });
    const fileStub = sinon.stub(client, 'fetchPinnedShareDeckFile').resolves({
      bytes: Buffer.from('body { color: red }'),
      contentType: 'text/css; charset=utf-8',
    });
    const response = await appRequest('shared/share-token/assets/theme.css');
    expect(response.status).to.equal(200);
    expect(await response.text()).to.equal('body { color: red }');
    expect(fileStub.firstCall.args[3]).to.equal('assets/theme.css');
    expect(resolveStub.calledOnce).to.equal(true);
  });
});
