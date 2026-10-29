import { expect } from 'chai';
import express from 'express';
import { AddressInfo } from 'net';
import { suppressShareBodyParserError, isShareTokenRequest } from '../../../src/modules/artifacts/services/share-request-privacy';

describe('share bearer request privacy', () => {
  it('recognizes only token endpoints', () => {
    expect(isShareTokenRequest('/api/v1/artifact-shares/content')).to.equal(true);
    expect(isShareTokenRequest('/api/v1/artifact-shares/metadata')).to.equal(true);
    expect(isShareTokenRequest('/API/V1/ARTIFACT-SHARES/CONTENT/')).to.equal(true);
    expect(isShareTokenRequest('/api/v1/artifact-shares/unknown')).to.equal(true);
    expect(isShareTokenRequest('/api/v1/artifacts')).to.equal(false);
  });

  it('suppresses malformed JSON body errors on token endpoints', async () => {
    const app = express();
    let forwarded = false;
    app.use(express.json());
    app.use(suppressShareBodyParserError);
    app.use((error: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
      forwarded = true;
      res.status(500).send(String(error));
    });
    const server = app.listen(0);
    try {
      const port = (server.address() as AddressInfo).port;
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/artifact-shares/content`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: '{"token":"sensitive-secret"',
      });
      expect(response.status).to.equal(404);
      expect(await response.text()).not.to.include('sensitive-secret');
      expect(response.headers.get('cache-control')).to.include('no-store');
      expect(forwarded).to.equal(false);
    } finally { server.close(); }
  });
});
