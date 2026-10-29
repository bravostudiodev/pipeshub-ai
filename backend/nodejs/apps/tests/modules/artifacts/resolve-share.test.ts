import { expect } from 'chai';
import sinon from 'sinon';
import * as repository from '../../../src/modules/artifacts/services/share-repository';
import * as owner from '../../../src/modules/artifacts/services/share-owner';
import { resolveShare } from '../../../src/modules/artifacts/services/resolve-share';

describe('share authority resolution', () => {
  afterEach(() => sinon.restore());
  const share = { _id: 'share', artifactId: 'artifact', version: 1, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain', orgId: 'org', ownerId: 'owner' };

  it('returns only scoped authority after fresh account and artifact checks', async () => {
    const find = sinon.stub(repository, 'findActiveShare').resolves(share as never);
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    const authorize = sinon.stub().resolves(true);
    const result = await resolveShare('token', authorize);
    expect(result).to.deep.equal({ artifactId: 'artifact', version: 1, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain', orgId: 'org', ownerId: 'owner' });
    expect(find.callCount).to.equal(2);
    expect(authorize.firstCall.args[0]).to.deep.equal(result);
  });

  it('rejects a link revoked while authority was being checked', async () => {
    const find = sinon.stub(repository, 'findActiveShare');
    find.onFirstCall().resolves(share as never);
    find.onSecondCall().resolves(null);
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    expect(await resolveShare('token', async () => true)).to.equal(null);
  });

  it('does not authorize an inactive owner', async () => {
    sinon.stub(repository, 'findActiveShare').resolves(share as never);
    sinon.stub(owner, 'isShareOwnerActive').resolves(false);
    const authorize = sinon.stub().resolves(true);
    expect(await resolveShare('token', authorize)).to.equal(null);
    expect(authorize.called).to.equal(false);
  });

  it('fails closed when authorization fails', async () => {
    sinon.stub(repository, 'findActiveShare').resolves(share as never);
    sinon.stub(owner, 'isShareOwnerActive').resolves(true);
    expect(await resolveShare('token', async () => false)).to.equal(null);
    try { await resolveShare('token', async () => { throw new Error('offline'); }); expect.fail(); }
    catch (error) { expect((error as Error).message).to.equal('offline'); }
  });
});
