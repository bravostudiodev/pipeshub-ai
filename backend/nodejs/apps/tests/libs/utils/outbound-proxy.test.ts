import { expect } from 'chai';
import { selectRoute, OutboundProxyConfigError } from '../../../src/libs/utils/outbound-proxy';

const PROXY = 'http://proxy.corp.example:3128';

describe('outbound-proxy selectRoute', () => {
  it('is direct when no proxy is configured', () => {
    expect(selectRoute('https://api.openai.com/v1', {})).to.deep.equal({
      via: 'direct',
      reason: 'no_proxy_configured',
    });
  });

  for (const url of [
    'https://api.openai.com/v1/models',
    'https://accounts.google.com/o/oauth2/token',
    'https://8.8.8.8/',
    'http://[2606:4700::1]/',
  ]) {
    it(`proxies ${url}`, () => {
      const route = selectRoute(url, { OUTBOUND_PROXY_URL: PROXY });
      expect(route).to.deep.equal({ via: 'proxy', reason: 'external', proxyUrl: PROXY });
    });
  }

  for (const url of [
    'http://localhost:8088/',
    'http://127.0.0.1:3000/',
    'http://[::1]:8000/',
    'http://10.1.2.3/',
    'http://172.20.0.5/',
    'http://192.168.1.1/',
    'http://qdrant:6333/',
    'http://a.ns.svc/',
    'http://q.ns.svc.cluster.local:8000/',
  ]) {
    it(`keeps ${url} direct`, () => {
      const route = selectRoute(url, { OUTBOUND_PROXY_URL: PROXY });
      expect(route.via).to.equal('direct');
      expect(route.proxyUrl).to.equal(undefined);
    });
  }

  it('keeps only explicitly bypassed hosts direct', () => {
    const env = {
      OUTBOUND_PROXY_URL: PROXY,
      CONNECTOR_ENDPOINT: 'http://connectors.example.org:8088',
      OUTBOUND_PROXY_BYPASS: 'litellm.corp.example',
    };
    expect(selectRoute('http://connectors.example.org/x', env).via).to.equal('proxy');
    expect(selectRoute('https://litellm.corp.example/v1', env).via).to.equal('direct');
    expect(selectRoute('https://a.mesh.example/', env).via).to.equal('proxy');
    expect(selectRoute('http://203.0.113.9/', env).via).to.equal('proxy');
    expect(selectRoute('https://mesh.example.evil.com/', env).via).to.equal('proxy');
    expect(selectRoute('https://evil-svc.com/', env).via).to.equal('proxy');
  });

  it('fails loudly on an invalid proxy URL', () => {
    for (const bad of ['ftp://p:21', 'proxy:3128', 'http://']) {
      expect(() => selectRoute('https://x.com/', { OUTBOUND_PROXY_URL: bad })).to.throw(
        OutboundProxyConfigError,
      );
    }
  });
});
