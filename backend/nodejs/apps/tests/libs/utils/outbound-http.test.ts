import { expect } from 'chai';
import axios from 'axios';
import http from 'http';
import { AddressInfo } from 'net';
import {
  installOutboundHttp,
  uninstallOutboundHttp,
  setOutboundLogSink,
} from '../../../src/libs/utils/outbound-http';

const EXTERNAL = '203.0.113.10';
const SECRETS = ['s3cr3t-token', 'sk-live-key', 'hunter2', '/private/path'];

interface Fake {
  server: http.Server;
  port: number;
  lines: string[];
  body: string;
}

async function fake(body: string): Promise<Fake> {
  const state = { lines: [] as string[], body } as Fake;
  state.server = http.createServer((req, res) => {
    state.lines.push(`${req.method} ${req.url}`);
    res.writeHead(200, { 'content-type': 'text/plain', connection: 'close' });
    res.end(state.body);
  });
  state.server.on('connect', (req, socket) => {
    state.lines.push(`CONNECT ${req.url}`);
    socket.end('HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n');
  });
  await new Promise<void>((resolve) => state.server.listen(0, '127.0.0.1', resolve));
  state.port = (state.server.address() as AddressInfo).port;
  return state;
}

function plainGet(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => resolve(data));
      })
      .on('error', reject);
  });
}

describe('outbound-http', () => {
  let proxy: Fake;
  let service: Fake;
  let events: Record<string, unknown>[];
  const saved = { ...process.env };

  beforeEach(async () => {
    proxy = await fake('via-proxy');
    service = await fake('direct');
    events = [];
    process.env.OUTBOUND_PROXY_URL = `http://user:hunter2@127.0.0.1:${proxy.port}`;
    setOutboundLogSink((_level, fields) => events.push(fields));
    installOutboundHttp();
  });

  afterEach(async () => {
    uninstallOutboundHttp();
    process.env = { ...saved };
    await Promise.all(
      [proxy, service].map((f) => new Promise((r) => f.server.close(() => r(undefined)))),
    );
  });

  const noSecrets = () => {
    const text = JSON.stringify(events);
    for (const secret of SECRETS) expect(text).to.not.contain(secret);
  };

  it('sends an external http.get through the proxy and logs it safely', async () => {
    const url = `http://${EXTERNAL}:8080/private/path?api_key=s3cr3t-token`;
    expect(await plainGet(url)).to.equal('via-proxy');
    expect(proxy.lines).to.deep.equal([`GET ${url}`]);
    expect(events).to.have.length(1);
    expect(events[0]).to.include({
      dest_host: EXTERNAL, dest_port: 8080, method: 'GET', via: 'proxy', route_reason: 'external',
      outcome: 'response', status: 200,
    });
    noSecrets();
  });

  it('keeps in-cluster http.get direct', async () => {
    expect(await plainGet(`http://127.0.0.1:${service.port}/x?token=s3cr3t-token`)).to.equal('direct');
    expect(proxy.lines).to.deep.equal([]);
    expect(events[0]).to.include({ via: 'direct', route_reason: 'in_cluster', status: 200 });
    noSecrets();
  });

  it('tunnels external https through CONNECT to the hostname and logs the proxy refusal', async () => {
    const https = await import('https');
    await new Promise<void>((resolve) => {
      https.get(`https://${EXTERNAL}/v1/models`, () => resolve()).on('error', () => resolve());
    });
    expect(proxy.lines).to.deep.equal([`CONNECT ${EXTERNAL}:443`]);
    // https-proxy-agent hands the refused CONNECT back as the response, so it logs as its status
    expect(events[0]).to.include({ via: 'proxy', status: 502, dest_host: EXTERNAL });
  });

  it('routes axios by destination', async () => {
    const external = await axios.get(`http://${EXTERNAL}/a?token=s3cr3t-token`, {
      headers: { Authorization: 'Bearer sk-live-key' },
    });
    const internal = await axios.get(`http://127.0.0.1:${service.port}/b`);
    expect(external.data).to.equal('via-proxy');
    expect(internal.data).to.equal('direct');
    expect(proxy.lines).to.deep.equal([`GET http://${EXTERNAL}/a?token=s3cr3t-token`]);
    expect(events.map((e) => e.via)).to.deep.equal(['proxy', 'direct']);
    noSecrets();
  });

  it('routes global fetch by destination', async () => {
    const external = await fetch(`http://${EXTERNAL}/f?token=s3cr3t-token`, {
      headers: { Authorization: 'Bearer sk-live-key' },
    });
    const internal = await fetch(`http://127.0.0.1:${service.port}/g`);
    expect(await external.text()).to.equal('via-proxy');
    expect(await internal.text()).to.equal('direct');
    expect(proxy.lines).to.have.length(1);
    expect(proxy.lines[0]).to.contain(EXTERNAL);
    expect(events.map((e) => [e.via, e.status])).to.deep.equal([['proxy', 200], ['direct', 200]]);
    expect(events.every((e) => e.category === 'fetch')).to.equal(true);
    noSecrets();
  });

  it('logs a failed connection', async () => {
    const dead = await fake('x');
    const port = dead.port;
    await new Promise((r) => dead.server.close(() => r(undefined)));
    let failed = false;
    await plainGet(`http://127.0.0.1:${port}/`).catch(() => (failed = true));
    expect(failed).to.equal(true);
    expect(events[0]).to.include({ via: 'direct', outcome: 'connect_error' });
  });

  it('flags an SDK that goes around the proxy with its own agent', async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { S3 } = require('aws-sdk');
    const s3 = new S3({
      region: 'us-east-1', accessKeyId: 'a', secretAccessKey: 'b', maxRetries: 0,
      endpoint: `http://127.0.0.1:${service.port}`, s3ForcePathStyle: true,
    });
    await s3.listBuckets().promise().catch(() => undefined);
    expect(proxy.lines).to.deep.equal([]);
    expect(events[0]).to.include({ via: 'direct', route_reason: 'in_cluster' });
  });
});
