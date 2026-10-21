// Route policy for outbound HTTP, mirroring backend/python/app/utils/outbound_proxy.py:
// public destinations use OUTBOUND_PROXY_URL; loopback, private ranges, *.svc,
// *.cluster.local and dotless service names stay direct. Explicit internal FQDNs
// can be named in OUTBOUND_PROXY_BYPASS.
import { isIP } from 'net';

export const OUTBOUND_PROXY_URL_ENV = 'OUTBOUND_PROXY_URL';
export const OUTBOUND_PROXY_BYPASS_ENV = 'OUTBOUND_PROXY_BYPASS';

const LOCAL_SUFFIXES = ['.localhost', '.svc', '.cluster.local'];

export type Via = 'proxy' | 'direct';
export type RouteReason = 'external' | 'in_cluster' | 'configured_bypass' | 'no_proxy_configured';

export interface OutboundRoute {
  via: Via;
  reason: RouteReason;
  proxyUrl?: string;
}

export class OutboundProxyConfigError extends Error {}

type Env = Record<string, string | undefined>;

export function hostOf(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    const host = new URL(trimmed.includes('//') ? trimmed : `//${trimmed}`, 'http://x').hostname;
    return host ? host.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '') : undefined;
  } catch {
    return undefined;
  }
}

export function parseProxyUrl(raw: string | undefined): string | undefined {
  const value = (raw ?? '').trim();
  if (!value) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new OutboundProxyConfigError(`${OUTBOUND_PROXY_URL_ENV} is not a valid URL`);
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new OutboundProxyConfigError(
      `${OUTBOUND_PROXY_URL_ENV} must be an http:// or https:// URL with a host`,
    );
  }
  return value;
}

function ipv4ToInt(ip: string): number {
  return ip.split('.').reduce((acc, octet) => acc * 256 + Number(octet), 0);
}

function inCidr(ip: string, cidr: string): boolean {
  const [base, bitsRaw] = cidr.split('/');
  if (!base || isIP(base) !== 4 || isIP(ip) !== 4) return false;
  const bits = Number(bitsRaw);
  const size = 2 ** (32 - bits);
  return Math.floor(ipv4ToInt(ip) / size) === Math.floor(ipv4ToInt(base) / size);
}

const PRIVATE_V4 = ['127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16'];

function isPrivateV6(ip: string): boolean {
  const lower = ip.toLowerCase();
  if (lower === '::1') return true;
  if (lower.startsWith('::ffff:')) {
    const tail = lower.slice('::ffff:'.length);
    const words = tail.split(':');
    const high = Number.parseInt(words[0] ?? '', 16);
    const low = Number.parseInt(words[1] ?? '', 16);
    const mapped = words.length === 2
      ? [high >>> 8, high & 255, low >>> 8, low & 255].join('.')
      : tail;
    return PRIVATE_V4.some((c) => inCidr(mapped, c));
  }
  return /^f[cd]/.test(lower) || /^fe[89ab]/.test(lower);
}

function bypassReason(host: string, env: Env): RouteReason | undefined {
  const family = isIP(host);
  const extra = (env[OUTBOUND_PROXY_BYPASS_ENV] ?? '')
    .split(',')
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
  if (family === 4) {
    if (PRIVATE_V4.some((c) => inCidr(host, c))) return 'in_cluster';
  }
  if (family === 6 && isPrivateV6(host)) return 'in_cluster';

  const configured = new Set(['localhost']);
  for (const e of extra) {
    const h = hostOf(e);
    if (!h || e.includes('*') || e.includes('/') || e.startsWith('.')) {
      throw new OutboundProxyConfigError(`${OUTBOUND_PROXY_BYPASS_ENV} accepts exact hostnames only`);
    }
    configured.add(h);
  }
  if (configured.has(host)) return 'configured_bypass';
  if (family === 0) {
    if (LOCAL_SUFFIXES.some((s) => host.endsWith(s))) return 'in_cluster';
    if (!host.includes('.')) return 'in_cluster'; // Compose/Kubernetes service name
  }
  return undefined;
}

/** Throws OutboundProxyConfigError when OUTBOUND_PROXY_URL is set but invalid. */
export function selectRoute(url: string, env: Env = process.env): OutboundRoute {
  const proxyUrl = parseProxyUrl(env[OUTBOUND_PROXY_URL_ENV]);
  if (!proxyUrl) return { via: 'direct', reason: 'no_proxy_configured' };
  const host = hostOf(url);
  if (!host) return { via: 'direct', reason: 'in_cluster' };
  const reason = bypassReason(host, env);
  if (reason) return { via: 'direct', reason };
  return { via: 'proxy', reason: 'external', proxyUrl };
}
