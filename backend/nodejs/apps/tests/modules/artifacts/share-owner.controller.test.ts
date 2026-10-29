import { expect } from 'chai';
import sinon from 'sinon';
import { createArtifactShare, revokeArtifactShare } from '../../../src/modules/artifacts/controllers/share-owner.controller';
import * as owner from '../../../src/modules/artifacts/services/share-owner';
import * as repo from '../../../src/modules/artifacts/services/share-repository';
import * as connector from '../../../src/modules/tokens_manager/utils/connector.utils';
import { AppConfig } from '../../../src/modules/tokens_manager/config/config';

const config = { connectorBackend: 'http://connector' } as AppConfig;
function response() {
  const res: any = { set: sinon.stub(), status: sinon.stub(), json: sinon.stub(), end: sinon.stub() };
  res.status.returns(res);
  return res;
}
function request() {
  return { user: { userId: 'owner', orgId: 'org' }, params: { artifactId: 'artifact', shareId: 'id' }, body: { version: 2, expiresInDays: 7 }, headers: { authorization: 'session' } } as any;
}

describe('artifact share owner controllers', () => {
  afterEach(() => sinon.restore());
  it('creates only after active account and artifact ownership checks', async () => {
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    const check = sinon.stub(connector, 'executeConnectorCommand').resolves({ statusCode: 200, data: { authorized: true, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain' } } as never);
    const insert = sinon.stub(repo, 'insertShare').resolves({ id: 'id', token: 'secret', expiresAt: new Date() });
    const res = response();
    await createArtifactShare(config)(request(), res, sinon.stub());
    expect(check.firstCall.args[0]).to.include('/artifact/share-authorization?version=2');
    expect(insert.firstCall.args[0]).to.include({ artifactId: 'artifact', version: 2, orgId: 'org', ownerId: 'owner' });
    expect(res.status.calledWith(201)).to.equal(true);
  });
  it('never persists if artifact authorization fails', async () => {
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    sinon.stub(connector, 'executeConnectorCommand').resolves({ statusCode: 404 } as never);
    const insert = sinon.stub(repo, 'insertShare');
    const res = response();
    await createArtifactShare(config)(request(), res, sinon.stub());
    expect(res.status.calledWith(404)).to.equal(true);
    expect(insert.called).to.equal(false);
  });
  it('revokes only with authenticated caller and artifact identity', async () => {
    const revoke = sinon.stub(repo, 'revokeShare').resolves(true);
    const res = response();
    await revokeArtifactShare()(request(), res, sinon.stub());
    expect(revoke.firstCall.args[0]).to.deep.equal({ shareId: 'id', artifactId: 'artifact', orgId: 'org', ownerId: 'owner' });
    expect(res.status.calledWith(204)).to.equal(true);
  });
});
