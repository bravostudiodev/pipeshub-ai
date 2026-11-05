import { expect } from 'chai';
import sinon from 'sinon';
import { Response } from 'express';
import { setShareDownloadHeaders, setShareResponsePrivacyHeaders } from '../../../src/modules/artifacts/services/share-response';

describe('shared content response headers', () => {
  it('forces untrusted content to download with restrictive security headers', () => {
    const set = sinon.spy();
    setShareDownloadHeaders({ set } as unknown as Response);
    const headers = set.firstCall.args[0];
    expect(headers['Content-Disposition']).to.match(/^attachment/);
    expect(headers['Content-Type']).to.equal('application/octet-stream');
    expect(headers['X-Content-Type-Options']).to.equal('nosniff');
    expect(headers['Content-Security-Policy']).to.include("default-src 'none'");
    expect(headers['Content-Security-Policy']).to.include('sandbox');
    expect(headers['Cache-Control']).to.include('no-store');
    expect(headers['Referrer-Policy']).to.equal('no-referrer');
  });

  it('prohibits caching and referrer leakage for metadata and errors', () => {
    const set = sinon.spy();
    setShareResponsePrivacyHeaders({ set } as unknown as Response);
    expect(set.firstCall.args[0]).to.include({ 'Cache-Control': 'no-store, private', 'Referrer-Policy': 'no-referrer' });
  });
});
