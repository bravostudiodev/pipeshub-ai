import { expect } from 'chai';
import { createShareToken, hashShareToken } from '../../../src/modules/artifacts/services/share-token';
import { ArtifactShareModel } from '../../../src/modules/artifacts/schema/artifact-share.schema';

describe('artifact share persistence foundation', () => {
  it('generates distinct canonical 256-bit tokens and stores only their hashes', () => {
    const a = createShareToken();
    const b = createShareToken();
    expect(a).not.to.equal(b);
    expect(hashShareToken(a)).to.match(/^[0-9a-f]{64}$/);
    expect(hashShareToken(a)).not.to.equal(a);
    expect(hashShareToken(a)).to.equal(hashShareToken(a));
  });

  it('rejects malformed and non-canonical tokens', () => {
    for (const value of [null, '', 'a'.repeat(42), 'a'.repeat(44), 'a'.repeat(42) + 'b', '../secret']) {
      expect(hashShareToken(value)).to.equal(null);
    }
  });

  it('requires a hash and a positive integer pinned version', () => {
    const base = {
      tokenHash: hashShareToken(createShareToken()), artifactId: 'artifact', version: 1, contentHash: 'a'.repeat(64), name: 'file.html', mimeType: 'text/html',
      orgId: 'org', ownerId: 'owner', expiresAt: new Date(Date.now() + 1000),
    };
    expect(new ArtifactShareModel(base).validateSync()).to.equal(undefined);
    expect(new ArtifactShareModel({ ...base, version: 1.5 }).validateSync()).to.exist;
    expect(new ArtifactShareModel({ ...base, tokenHash: 'raw-token' }).validateSync()).to.exist;
    expect(() => new ArtifactShareModel({ ...base, token: 'raw-token' })).to.throw();
  });
});
