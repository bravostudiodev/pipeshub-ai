import { expect } from 'chai';
import express from 'express';
import { AddressInfo } from 'net';
import sinon from 'sinon';
import { AppConfig } from '../../../src/modules/tokens_manager/config/config';
import { createShareContentRouter } from '../../../src/modules/artifacts/routes/share-content.routes';
import * as resolve from '../../../src/modules/artifacts/services/resolve-share';
import * as client from '../../../src/modules/artifacts/services/share-content-client';

describe('share content over HTTP', () => {
  afterEach(() => sinon.restore());
  const config = { connectorBackend: 'http://connector', scopedJwtSecret: 'secret' } as AppConfig;
  const authority = { orgId: 'org', ownerId: 'owner', artifactId: 'artifact', version: 1, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain' };

  async function request(token: string) {
    const app = express();
    app.use(express.json());
    app.use('/api/v1/artifact-shares', createShareContentRouter(config));
    const server = app.listen(0);
    try {
      const port = (server.address() as AddressInfo).port;
      return await fetch(`http://127.0.0.1:${port}/api/v1/artifact-shares/content`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token }),
      });
    } finally { server.close(); }
  }

  it('returns only pinned bytes with safe download headers', async () => {
    sinon.stub(resolve, 'resolveShare').callsFake(async (_token, authorize) => {
      await authorize(authority);
      return authority;
    });
    sinon.stub(client, 'fetchPinnedShareContent').resolves(Buffer.from('pinned'));
    const response = await request('secret');
    expect(response.status).to.equal(200);
    expect(await response.text()).to.equal('pinned');
    expect(response.headers.get('content-disposition')).to.match(/^attachment/);
    expect(response.headers.get('cache-control')).to.include('no-store');
  });

  it('uses the same unavailable response on missing share or internal failure', async () => {
    const stub = sinon.stub(resolve, 'resolveShare');
    stub.onFirstCall().resolves(null);
    stub.onSecondCall().rejects(new Error('secret details'));
    for (let i = 0; i < 2; i++) {
      const response = await request('secret');
      expect(response.status).to.equal(404);
      expect(await response.json()).to.deep.equal({ message: 'This artifact is unavailable.' });
      expect(response.headers.get('cache-control')).to.include('no-store');
    }
  });
});
