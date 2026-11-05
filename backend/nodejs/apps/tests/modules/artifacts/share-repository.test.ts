import { expect } from 'chai';
import sinon from 'sinon';
import { ArtifactShareModel } from '../../../src/modules/artifacts/schema/artifact-share.schema';
import { findActiveShare, insertShare, listActiveShares, recoverShareToken, revokeShare } from '../../../src/modules/artifacts/services/share-repository';
import { hashShareToken } from '../../../src/modules/artifacts/services/share-token';

describe('artifact share repository', () => {
  afterEach(() => sinon.restore());

  it('persists a hash and encrypted copy, never the plaintext token', async () => {
    sinon.stub(process, 'env').value({ ...process.env, SECRET_KEY: 'test-key' });
    const create = sinon.stub(ArtifactShareModel, 'create').resolves({ _id: 'id', expiresAt: new Date('2030-01-01') } as never);
    const expiresAt = new Date(Date.now() + 60000);
    const result = await insertShare({ artifactId: 'a', version: 2, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain', ownerId: 'u', orgId: 'o', expiresAt });
    const saved = create.firstCall.args[0] as unknown as Record<string, unknown>;
    expect(saved.tokenHash).to.equal(hashShareToken(result.token));
    expect(saved).not.to.have.property('token');
    expect(String(saved.encryptedToken)).not.to.include(result.token);
  });

  it('rejects malformed tokens before accessing persistence', async () => {
    const find = sinon.stub(ArtifactShareModel, 'findOne');
    expect(await findActiveShare('bad')).to.equal(null);
    expect(find.called).to.equal(false);
  });

  it('checks revocation and expiration on every lookup and propagates database failures', async () => {
    const exec = sinon.stub().rejects(new Error('database unavailable'));
    const find = sinon.stub(ArtifactShareModel, 'findOne').returns({ lean: () => ({ exec }) } as never);
    const token = 'A'.repeat(43);
    try { await findActiveShare(token); expect.fail('expected failure'); } catch (e) {
      expect((e as Error).message).to.equal('database unavailable');
    }
    const query = find.firstCall.args[0] as Record<string, unknown>;
    expect(query.tokenHash).to.equal(hashShareToken(token));
    expect(query.revokedAt).to.equal(null);
    expect(query.expiresAt).to.have.property('$gt').that.is.instanceOf(Date);
  });

  it('lists only active shares belonging to the owner without token hashes', async () => {
    const select = sinon.stub().returns({ sort: () => ({ lean: () => ({ exec: async () => [] }) }) });
    const find = sinon.stub(ArtifactShareModel, 'find').returns({ select } as never);
    await listActiveShares({ artifactId: 'a', orgId: 'o', ownerId: 'u' });
    const filter = find.firstCall.args[0] as Record<string, unknown>;
    expect(filter).to.include({ artifactId: 'a', orgId: 'o', ownerId: 'u', revokedAt: null });
    expect(filter.expiresAt).to.have.property('$gt').that.is.instanceOf(Date);
    expect(select.firstCall.args[0]).to.equal('_id version createdAt expiresAt +encryptedToken');
  });

  it('indicates copy availability without returning encrypted bearer values', async () => {
    sinon.stub(ArtifactShareModel, 'find').returns({ select: () => ({ sort: () => ({ lean: () => ({ exec: async () => [
      { _id: 'new', version: 1, encryptedToken: 'encrypted-secret' },
      { _id: 'old', version: 1 },
    ] }) }) }) } as never);
    const result = await listActiveShares({ artifactId: 'a', orgId: 'o', ownerId: 'u' });
    expect(result.map((share) => share.canCopy)).to.deep.equal([true, false]);
    expect(JSON.stringify(result)).not.to.include('encrypted-secret');
  });

  it('recovers only a live share scoped to owner, organization, and artifact', async () => {
    sinon.stub(process, 'env').value({ ...process.env, SECRET_KEY: 'test-key' });
    const create = sinon.stub(ArtifactShareModel, 'create').resolves({ _id: 'id', expiresAt: new Date('2030-01-01') } as never);
    const saved = await insertShare({ artifactId: 'a', version: 2, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain', ownerId: 'u', orgId: 'o', expiresAt: new Date(Date.now() + 60000) });
    const record = create.firstCall.args[0] as any;
    const find = sinon.stub(ArtifactShareModel, 'findOne').returns({ select: () => ({ lean: () => ({ exec: async () => record }) }) } as never);
    expect(await recoverShareToken({ shareId: 'id', artifactId: 'a', orgId: 'o', ownerId: 'u' })).to.equal(saved.token);
    expect(find.firstCall.args[0]).to.include({ _id: 'id', artifactId: 'a', orgId: 'o', ownerId: 'u', revokedAt: null });
    expect(await recoverShareToken({ shareId: 'id', artifactId: 'a', orgId: 'other', ownerId: 'u' })).to.equal(null);
  });

  it('scopes revocation to owner, organisation, artifact and active link', async () => {
    const update = sinon.stub(ArtifactShareModel, 'updateOne').returns({ exec: async () => ({ modifiedCount: 1 }) } as never);
    expect(await revokeShare({ shareId: 's', artifactId: 'a', orgId: 'o', ownerId: 'u' })).to.equal(true);
    const filter = update.firstCall.args[0] as Record<string, unknown>;
    expect(filter).to.include({ _id: 's', artifactId: 'a', orgId: 'o', ownerId: 'u', revokedAt: null });
    expect(filter.expiresAt).to.have.property('$gt').that.is.instanceOf(Date);
  });
});
