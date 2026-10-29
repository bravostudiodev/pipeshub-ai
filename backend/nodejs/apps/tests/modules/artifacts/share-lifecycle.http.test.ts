import { expect } from 'chai';
import express from 'express';
import { AddressInfo } from 'net';
import sinon from 'sinon';
import { AppConfig } from '../../../src/modules/tokens_manager/config/config';
import { createArtifactShare, revokeArtifactShare } from '../../../src/modules/artifacts/controllers/share-owner.controller';
import { createShareContentRouter } from '../../../src/modules/artifacts/routes/share-content.routes';
import * as connector from '../../../src/modules/tokens_manager/utils/connector.utils';
import * as repository from '../../../src/modules/artifacts/services/share-repository';
import * as owner from '../../../src/modules/artifacts/services/share-owner';
import * as content from '../../../src/modules/artifacts/services/share-content-client';

const config = { connectorBackend: 'http://connector', scopedJwtSecret: 'secret' } as AppConfig;

describe('share lifecycle over HTTP with mocked persistence and connector', () => {
  afterEach(() => sinon.restore());
  it('pins a version, denies another owner revocation, and fails after revocation', async () => {
    let active = true;
    let stored: any;
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    sinon.stub(connector, 'executeConnectorCommand').resolves({ statusCode: 200, data: { authorized: true, contentHash: 'a'.repeat(64), name: 'file.txt', mimeType: 'text/plain' } } as never);
    sinon.stub(repository, 'insertShare').callsFake(async (input) => {
      stored = { ...input, _id: 'share' };
      return { id: 'share', token: 'bearer', expiresAt: input.expiresAt };
    });
    sinon.stub(repository, 'findActiveShare').callsFake(async (token) => active && token === 'bearer' ? stored : null);
    sinon.stub(repository, 'revokeShare').callsFake(async (input) => {
      if (input.ownerId !== stored.ownerId || input.orgId !== stored.orgId || !active) return false;
      active = false;
      return true;
    });
    const fetchContent = sinon.stub(content, 'fetchPinnedShareContent').resolves(Buffer.from('version one'));
    const app = express();
    app.use(express.json());
    app.use('/api/v1/artifact-shares', createShareContentRouter(config));
    app.use((req, _res, next) => { (req as any).user = { userId: req.headers['x-test-user'], orgId: req.headers['x-test-org'] }; next(); });
    app.post('/artifact/:artifactId/shares', createArtifactShare(config));
    app.delete('/artifact/:artifactId/shares/:shareId', revokeArtifactShare());
    const server = app.listen(0);
    try {
      const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
      const ownerHeaders = { 'content-type': 'application/json', 'x-test-user': 'owner', 'x-test-org': 'org' };
      const created = await fetch(`${base}/artifact/artifact/shares`, { method: 'POST', headers: ownerHeaders, body: JSON.stringify({ version: 1, expiresInDays: 7 }) });
      expect(created.status).to.equal(201);
      const sendToken = () => fetch(`${base}/api/v1/artifact-shares/content`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token: 'bearer' }) });
      const first = await sendToken();
      expect(await first.text()).to.equal('version one');
      expect(fetchContent.firstCall.args[2].version).to.equal(1);
      const other = await fetch(`${base}/artifact/artifact/shares/share`, { method: 'DELETE', headers: { 'x-test-user': 'reader', 'x-test-org': 'org' } });
      expect(other.status).to.equal(404);
      const revoked = await fetch(`${base}/artifact/artifact/shares/share`, { method: 'DELETE', headers: ownerHeaders });
      expect(revoked.status).to.equal(204);
      expect((await sendToken()).status).to.equal(404);
      const metadata = await fetch(`${base}/api/v1/artifact-shares/metadata`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ token: 'bearer' }) });
      expect(metadata.status).to.equal(404);
    } finally { server.close(); }
  });
});
