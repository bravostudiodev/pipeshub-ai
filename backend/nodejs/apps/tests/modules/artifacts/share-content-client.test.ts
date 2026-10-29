import { expect } from 'chai';
import sinon from 'sinon';
import jwt from 'jsonwebtoken';
import { fetchPinnedShareContent } from '../../../src/modules/artifacts/services/share-content-client';

describe('share content connector client', () => {
  afterEach(() => sinon.restore());
  const authority = { artifactId: 'artifact', version: 2, contentHash: 'a'.repeat(64), name: 'file', mimeType: 'text/plain', orgId: 'org', ownerId: 'owner' };

  it('requests the pinned version using a short-lived dedicated service token', async () => {
    const fetch = sinon.stub(globalThis, 'fetch').resolves(new Response('pinned'));
    const result = await fetchPinnedShareContent('http://connector:8088', 'secret', authority);
    expect(result.toString()).to.equal('pinned');
    const [url, options] = fetch.firstCall.args;
    expect(String(url)).to.equal('http://connector:8088/api/v1/internal/artifact-share/content');
    const bearer = (options?.headers as Record<string, string>).Authorization;
    const claims = jwt.verify(bearer.slice(7), 'secret') as jwt.JwtPayload;
    expect(claims).to.include({ orgId: 'org', userId: 'owner', artifactId: 'artifact', version: 2 });
    expect(claims.scopes).to.deep.equal(['artifact-share:content']);
    expect(claims.exp! - claims.iat!).to.equal(60);
    expect(options?.redirect).to.equal('error');
  });

  it('fails without a secret or when the service refuses', async () => {
    const fetch = sinon.stub(globalThis, 'fetch').resolves(new Response('private failure', { status: 500 }));
    for (const secret of ['', 'secret']) {
      try { await fetchPinnedShareContent('http://connector', secret, authority); expect.fail('expected failure'); }
      catch (error) { expect((error as Error).message).to.equal('Share content service unavailable'); }
    }
    expect(fetch.calledOnce).to.equal(true);
  });
});
