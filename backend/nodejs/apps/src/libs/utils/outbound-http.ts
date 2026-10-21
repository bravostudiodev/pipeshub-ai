// Routes public outbound HTTP through OUTBOUND_PROXY_URL and logs every request, for the
// Node clients the API uses: global fetch (undici), axios, and anything built on
// http/https.request (including axios and OAuth clients using that stack).
//
// Each request logs one `outbound_http` entry: destination host and port, method, via
// (proxy|direct), route reason, category, outcome and the request id. Paths, queries,
// headers, cookies and bodies are never logged.
import axios from 'axios';
import http from 'http';
import https from 'https';
import { Dispatcher, Agent, ProxyAgent, setGlobalDispatcher } from 'undici';
import { HttpsProxyAgent } from 'https-proxy-agent';
import { Logger } from '../services/logger.service';
import { getRootId } from '../context/request-context';
import { hostOf, OutboundRoute, selectRoute, OUTBOUND_PROXY_URL_ENV, parseProxyUrl } from './outbound-proxy';

export type OutboundLogSink = (level: 'info' | 'warn', fields: Record<string, unknown>) => void;

const DEFAULT_PORTS: Record<string, number> = { 'http:': 80, 'https:': 443 };
let sink: OutboundLogSink = (level, fields) => {
  const logger = Logger.getInstance({ service: 'outbound_http' });
  logger[level]('outbound_http', fields);
};

export function setOutboundLogSink(next: OutboundLogSink | undefined): void {
  sink = next ?? sink;
}

export function destination(url: string): { host: string; port?: number } {
  try {
    const parsed = new URL(url);
    return {
      host: hostOf(url) ?? 'unknown',
      port: parsed.port ? Number(parsed.port) : DEFAULT_PORTS[parsed.protocol],
    };
  } catch {
    return { host: 'unparseable' };
  }
}

export function classifyError(err: unknown): string {
  const name = `${(err as Error)?.name ?? ''} ${(err as { code?: string })?.code ?? ''}`.toLowerCase();
  if (name.includes('proxy')) return 'proxy_error';
  if (name.includes('timeout') || name.includes('etimedout') || name.includes('abort')) return 'timeout';
  if (name.includes('cert') || name.includes('ssl') || name.includes('tls')) return 'tls_error';
  if (name.includes('connect') || name.includes('econn') || name.includes('enotfound')) return 'connect_error';
  return 'error';
}

export interface OutboundEvent {
  category: string;
  method: string;
  url: string;
  via: string;
  reason: string;
  status?: number;
  error?: unknown;
  outcome?: string;
  durationMs?: number;
}

export function logOutbound(event: OutboundEvent): void {
  const { host, port } = destination(event.url);
  const category = event.category;
  let outcome = event.outcome ?? (event.error ? classifyError(event.error) : 'response');
  if (event.via === 'proxy' && (outcome === 'error' || outcome === 'connect_error')) outcome = 'proxy_error';
  const fields: Record<string, unknown> = {
    dest_host: host,
    dest_port: port,
    method: event.method.toUpperCase().slice(0, 16),
    via: event.via,
    route_reason: event.reason,
    category,
    outcome,
    status: event.status,
    error_type: event.error ? ((event.error as Error).name ?? 'Error') : undefined,
    duration_ms: event.durationMs === undefined ? undefined : Math.round(event.durationMs * 10) / 10,
    request_id: getRootId(),
  };
  for (const key of Object.keys(fields)) if (fields[key] === undefined) delete fields[key];
  sink(outcome === 'response' && event.reason !== 'proxy_not_applied' ? 'info' : 'warn', fields);
}

function safeRoute(url: string): OutboundRoute {
  try {
    return selectRoute(url);
  } catch {
    return { via: 'direct', reason: 'no_proxy_configured' };
  }
}

// ---------------------------------------------------------------- fetch (undici)

const HANDLER_METHODS = [
  'onConnect', 'onError', 'onUpgrade', 'onResponseStarted', 'onHeaders', 'onData',
  'onComplete', 'onBodySent', 'onRequestSent',
] as const;

export class RoutingDispatcher extends Dispatcher {
  private readonly direct = new Agent();
  private readonly proxies = new Map<string, ProxyAgent>();

  // https origins tunnel with CONNECT; plain-http origins are forwarded as absolute-URI
  // requests, because proxies commonly refuse CONNECT to port 80.
  private proxyAgent(proxyUrl: string, tunnel: boolean): ProxyAgent {
    const key = `${tunnel ? 'tunnel' : 'forward'}|${proxyUrl}`;
    let agent = this.proxies.get(key);
    if (!agent) {
      agent = new ProxyAgent({ uri: proxyUrl, proxyTunnel: tunnel });
      this.proxies.set(key, agent);
    }
    return agent;
  }

  override dispatch(opts: Dispatcher.DispatchOptions, handler: Dispatcher.DispatchHandlers): boolean {
    const origin = String(opts.origin ?? '');
    const route = safeRoute(origin);
    const started = performance.now();
    const base = { category: 'fetch', method: String(opts.method), url: origin, via: route.via, reason: route.reason };
    let logged = false;
    const once = (extra: Partial<OutboundEvent>): void => {
      if (logged) return;
      logged = true;
      logOutbound({ ...base, ...extra, durationMs: performance.now() - started });
    };
    const wrapped: Record<string, unknown> = {};
    const target = handler as unknown as Record<string, (...args: unknown[]) => unknown>;
    for (const name of HANDLER_METHODS) {
      if (typeof target[name] !== 'function') continue;
      wrapped[name] = (...args: unknown[]): unknown => {
        if (name === 'onHeaders') once({ status: args[0] as number });
        if (name === 'onError') once({ error: args[0] });
        return target[name]?.(...args);
      };
    }
    const agent = route.via === 'proxy' && route.proxyUrl ? this.proxyAgent(route.proxyUrl, origin.startsWith('https:')) : this.direct;
    return agent.dispatch(opts, wrapped as unknown as Dispatcher.DispatchHandlers);
  }

  override async close(): Promise<void> {
    await this.direct.close();
    await Promise.all([...this.proxies.values()].map((p) => p.close()));
  }

  override async destroy(): Promise<void> {
    await this.direct.destroy();
    await Promise.all([...this.proxies.values()].map((p) => p.destroy()));
  }
}

// ---------------------------------------------------------------- http / https

type RequestFn = typeof http.request;
const proxyAgents = new Map<string, HttpsProxyAgent<string>>();

function tunnelAgent(proxyUrl: string): HttpsProxyAgent<string> {
  let agent = proxyAgents.get(proxyUrl);
  if (!agent) {
    agent = new HttpsProxyAgent(proxyUrl);
    proxyAgents.set(proxyUrl, agent);
  }
  return agent;
}

function normalize(args: unknown[]): { options: http.RequestOptions; cb?: (res: http.IncomingMessage) => void } {
  const [first, second, third] = args;
  let options: http.RequestOptions = {};
  let cb: ((res: http.IncomingMessage) => void) | undefined;
  if (typeof first === 'string' || first instanceof URL) {
    const u = new URL(String(first));
    options = {
      protocol: u.protocol,
      hostname: u.hostname.replace(/^\[|\]$/g, ''),
      port: u.port || undefined,
      path: `${u.pathname}${u.search}`,
      auth: u.username ? `${decodeURIComponent(u.username)}:${decodeURIComponent(u.password)}` : undefined,
    };
    if (typeof second === 'function') cb = second as typeof cb;
    else {
      Object.assign(options, second ?? {});
      cb = typeof third === 'function' ? (third as typeof cb) : undefined;
    }
  } else {
    options = { ...((first as http.RequestOptions) ?? {}) };
    cb = typeof second === 'function' ? (second as typeof cb) : undefined;
  }
  return { options, cb };
}

function targetUrl(options: http.RequestOptions, defaultProtocol: string): string {
  const protocol = options.protocol ?? defaultProtocol;
  const host = String(options.hostname ?? options.host ?? 'localhost');
  const port = options.port ? `:${options.port}` : '';
  return `${protocol}//${host.includes(':') ? `[${host}]` : host}${port}${options.path ?? '/'}`;
}

function wrapRequest(original: RequestFn, defaultProtocol: 'http:' | 'https:'): RequestFn {
  return function request(...args: unknown[]): http.ClientRequest {
    const { options, cb } = normalize(args);
    const url = targetUrl(options, defaultProtocol);
    const route = safeRoute(url);
    const started = performance.now();
    let via = route.via;
    // Only requests on a default agent are re-routed: a client that built its own agent
    // (custom tunnel, keep-alive pool) keeps it and is logged with what the policy says.
    const usesDefaultAgent = options.agent === undefined || options.agent === http.globalAgent || options.agent === https.globalAgent;
    if (route.via === 'proxy' && route.proxyUrl && usesDefaultAgent) {
      if ((options.protocol ?? defaultProtocol) === 'https:') {
        options.agent = tunnelAgent(route.proxyUrl);
      } else {
        // Plain HTTP goes to the proxy as an absolute-URI request (CONNECT to port 80 is
        // typically refused); the target host stays in Host.
        const proxy = new URL(route.proxyUrl);
        const host = options.headers && 'host' in options.headers ? undefined : String(options.hostname ?? options.host);
        options.headers = { ...(options.headers ?? {}), ...(host ? { host: `${host}${options.port ? `:${options.port}` : ''}` } : {}) };
        if (proxy.username) {
          (options.headers as Record<string, unknown>)['proxy-authorization'] =
            `Basic ${Buffer.from(`${decodeURIComponent(proxy.username)}:${decodeURIComponent(proxy.password)}`).toString('base64')}`;
        }
        options.path = url;
        options.hostname = proxy.hostname.replace(/^\[|\]$/g, '');
        options.host = undefined;
        options.port = proxy.port || (proxy.protocol === 'https:' ? 443 : 80);
        options.protocol = 'http:';
        options.agent = undefined;
      }
    } else if (route.via === 'proxy') {
      // A custom agent is not ours to rewrite; it counts as proxied only if it is a proxy agent.
      via = options.agent instanceof HttpsProxyAgent ? 'proxy' : 'direct';
    }
    const req = (original as (...a: unknown[]) => http.ClientRequest)(options, cb);
    const base = {
      category: 'http', method: String(options.method ?? 'GET'), url,
      via, reason: via === 'direct' && route.via === 'proxy' ? 'proxy_not_applied' : route.reason,
    };
    let logged = false;
    const once = (extra: Partial<OutboundEvent>): void => {
      if (logged) return;
      logged = true;
      logOutbound({ ...base, ...extra, durationMs: performance.now() - started });
    };
    req.once('response', (res) => {
      const squidError = String(res.headers['x-squid-error'] ?? '');
      const outcome = via === 'proxy' && (
        res.statusCode === 407 || squidError.toUpperCase().includes('ACCESS_DENIED')
      ) ? 'proxy_denied' : via === 'proxy' && squidError ? 'proxy_error' : undefined;
      once({ status: res.statusCode, outcome });
    });
    req.once('error', (error) => once({ error }));
    return req;
  } as RequestFn;
}

let installed = false;
const originals = { request: http.request, get: http.get, sRequest: https.request, sGet: https.get };

/** Restores the patched modules and the default fetch dispatcher; for tests. */
export function uninstallOutboundHttp(): void {
  if (!installed) return;
  installed = false;
  http.request = originals.request;
  http.get = originals.get;
  https.request = originals.sRequest;
  https.get = originals.sGet;
  setGlobalDispatcher(new Agent());
}

/** Idempotent. Throws OutboundProxyConfigError for an invalid OUTBOUND_PROXY_URL. */
export function installOutboundHttp(): void {
  if (installed) return;
  parseProxyUrl(process.env[OUTBOUND_PROXY_URL_ENV]);
  selectRoute('https://external.invalid'); // also validates OUTBOUND_PROXY_BYPASS
  installed = true;
  setGlobalDispatcher(new RoutingDispatcher());
  // axios would otherwise read HTTP_PROXY itself and forward https requests without a tunnel.
  axios.defaults.proxy = false;
  const httpRequest = wrapRequest(http.request, 'http:');
  const httpsRequest = wrapRequest(https.request, 'https:');
  http.request = httpRequest;
  https.request = httpsRequest;
  http.get = ((...args: unknown[]) => {
    const req = (httpRequest as (...a: unknown[]) => http.ClientRequest)(...args);
    req.end();
    return req;
  }) as typeof http.get;
  https.get = ((...args: unknown[]) => {
    const req = (httpsRequest as (...a: unknown[]) => http.ClientRequest)(...args);
    req.end();
    return req;
  }) as typeof https.get;
}
