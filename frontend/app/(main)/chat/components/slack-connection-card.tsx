'use client';

import { useCallback, useEffect, useState } from 'react';
import { Box, Button, DropdownMenu, Flex, IconButton, Text, TextField, Tooltip } from '@radix-ui/themes';
import { useTranslation } from 'react-i18next';
import { MaterialIcon } from '@/app/components/ui/MaterialIcon';
import { isProcessedError } from '@/lib/api';
import { McpServersApi } from '@/app/(main)/workspace/mcp-servers/api';
import { ConnectorsApi } from '@/app/(main)/workspace/connectors/api';
import { startConnectorSync } from '@/app/(main)/workspace/connectors/utils/connector-sync-actions';
import type { SlackConnectionStatus } from '@/app/(main)/workspace/mcp-servers/types';
import { useMcpOAuthPopup } from '@/app/(main)/workspace/mcp-servers/hooks/use-mcp-oauth-popup';

const initialStatus: SlackConnectionStatus = { configured: false, isConnected: false };
type Provider = 'slack' | 'notion' | 'miro' | 'atlassian' | 'gmail' | 'google-drive' | 'superhuman';

function McpConnectionCard({ provider }: { provider: Provider }) {
  const { t } = useTranslation();
  const name = provider === 'slack'
    ? 'Slack'
    : provider === 'notion'
      ? 'Notion'
      : provider === 'miro'
        ? 'Miro'
      : provider === 'atlassian'
        ? 'Jira'
        : provider === 'gmail'
          ? 'Gmail'
          : provider === 'google-drive'
            ? 'Google Drive'
            : 'Superhuman Docs / Coda';
  const i18nPrefix = `chat.${provider}Connection`;
  const statusRequest = provider === 'slack'
    ? McpServersApi.getSlackConnection
    : provider === 'notion'
      ? McpServersApi.getNotionConnection
      : provider === 'miro'
        ? McpServersApi.getMiroConnection
      : provider === 'atlassian'
        ? McpServersApi.getAtlassianConnection
        : provider === 'gmail'
          ? McpServersApi.getGmailConnection
          : provider === 'google-drive'
            ? McpServersApi.getGoogleDriveConnection
            : McpServersApi.getSuperhumanDocsConnection;
  const [connection, setConnection] = useState<SlackConnectionStatus>(initialStatus);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [tokenEntryOpen, setTokenEntryOpen] = useState(false);
  const [personalToken, setPersonalToken] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async (): Promise<SlackConnectionStatus> => {
    const next = await statusRequest();
    setConnection(next);
    return next;
  }, [statusRequest]);

  const verifyConnected = useCallback(async () => {
    try {
      return (await refreshStatus()).isConnected;
    } catch {
      return false;
    }
  }, [refreshStatus]);

  const { startOAuthPopup, status: oauthStatus } = useMcpOAuthPopup({
    verifyAuthenticated: verifyConnected,
    onVerified: () => {
      setWorking(false);
      setError(null);
    },
    onFailed: () => {
      setWorking(false);
      setError(t(`${i18nPrefix}.connectError`, { defaultValue: `${name} could not be connected. Please try again.` }));
    },
  });

  useEffect(() => {
    let active = true;
    void statusRequest()
      .then((next) => { if (active) setConnection(next); })
      .catch(() => {
        if (active) setError(t(`${i18nPrefix}.statusError`, { defaultValue: `Could not check ${name} right now.` }));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [statusRequest, t, i18nPrefix, name]);

  const connect = async () => {
    if (!connection.instanceId || working) return;
    setError(null);
    if (provider === 'superhuman') {
      setTokenEntryOpen(true);
      return;
    }
    setWorking(true);
    await startOAuthPopup(connection.instanceId);
  };

  const savePersonalToken = async () => {
    if (!connection.instanceId || !personalToken.trim() || working) return;
    setWorking(true);
    setError(null);
    try {
      await McpServersApi.authenticate(connection.instanceId, { apiToken: personalToken.trim() });
      setPersonalToken('');
      setTokenEntryOpen(false);
      await refreshStatus();
    } catch (cause) {
      setError(isProcessedError(cause)
        ? cause.message
        : t(`${i18nPrefix}.connectError`, { defaultValue: `Could not connect ${name}. Check your token and try again.` }));
    } finally {
      setWorking(false);
    }
  };

  const disconnect = async () => {
    if (!connection.instanceId || working) return;
    setWorking(true);
    setError(null);
    try {
      await McpServersApi.removeCredentials(connection.instanceId);
      await refreshStatus();
    } catch {
      setError(t(`${i18nPrefix}.disconnectError`, { defaultValue: `${name} could not be disconnected. Please try again.` }));
    } finally {
      setWorking(false);
    }
  };

  if (loading) return null;

  return (
    <Flex align="center" gap="2" style={{ minHeight: 36, flexShrink: 0 }} aria-label={t(`${i18nPrefix}.label`, { defaultValue: 'Connected integrations' })}>
      {connection.configured ? (
        <Flex
          direction="column"
          align="stretch"
          gap="2"
          px="2"
          py="1"
          style={{
            minHeight: 34,
            border: '1px solid var(--slate-5)',
            borderRadius: 'var(--radius-3)',
            background: 'var(--color-panel)',
          }}
        >
          <Flex align="center" gap="2">
            <img
              src={`/icons/connectors/${provider === 'superhuman' ? 'superhuman' : provider === 'google-drive' ? 'drive' : provider === 'atlassian' ? 'atlassian' : provider}.svg`}
              width={20}
              height={20}
              alt=""
            />
            <Text size="2" weight="medium" style={{ color: 'var(--slate-12)' }}>{name}</Text>
            {connection.isConnected ? (
              <Flex align="center" gap="1" aria-label={t(`${i18nPrefix}.connected`, { defaultValue: 'Connected' })}>
                <MaterialIcon name="check_circle" size={14} color="var(--jade-9)" />
                <Text size="1" color="gray">{t(`${i18nPrefix}.connected`, { defaultValue: 'Connected' })}</Text>
              </Flex>
            ) : (
              <>
                <Button size="1" variant="soft" onClick={() => void connect()} disabled={working}>
                  {working || (provider !== 'superhuman' && oauthStatus === 'authenticating')
                    ? t(`${i18nPrefix}.connecting`, { defaultValue: 'Connecting…' })
                    : connection.hasCredentials
                    ? t(`${i18nPrefix}.reconnect`, { defaultValue: 'Reconnect' })
                      : t(`${i18nPrefix}.connect`, { defaultValue: 'Connect' })}
                </Button>
                {provider === 'superhuman' && (
                  <a
                    href="/superhuman-guide"
                    target="_blank"
                    rel="noreferrer"
                    style={{ fontSize: 'var(--font-size-1)', color: 'var(--accent-11)', whiteSpace: 'nowrap' }}
                  >
                    How to get a token
                  </a>
                )}
              </>
            )}

            {connection.isConnected && (
              <DropdownMenu.Root>
                <Tooltip content={t(`${i18nPrefix}.options`, { defaultValue: `${name} options` })}>
                  <DropdownMenu.Trigger>
                    <IconButton size="1" variant="ghost" color="gray" aria-label={t(`${i18nPrefix}.options`, { defaultValue: `${name} options` })}>
                      <MaterialIcon name="more_vert" size={16} />
                    </IconButton>
                  </DropdownMenu.Trigger>
                </Tooltip>
                <DropdownMenu.Content align="start" sideOffset={4}>
                  <DropdownMenu.Item onSelect={() => void connect()}>
                    {t(`${i18nPrefix}.reconnect`, { defaultValue: 'Reconnect' })}
                  </DropdownMenu.Item>
                  <DropdownMenu.Item color="red" onSelect={() => void disconnect()}>
                    {t(`${i18nPrefix}.disconnect`, { defaultValue: 'Disconnect' })}
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            )}
          </Flex>

          {provider === 'superhuman' && tokenEntryOpen && (
            <Flex align="center" gap="2">
              <TextField.Root
                size="1"
                type="password"
                aria-label="Personal API token"
                placeholder="Paste your personal API token"
                value={personalToken}
                onChange={(event) => setPersonalToken(event.target.value)}
                autoComplete="off"
                style={{ width: 230 }}
              />
              <Button size="1" variant="solid" onClick={() => void savePersonalToken()} disabled={!personalToken.trim() || working}>
                {working ? 'Connecting…' : 'Connect'}
              </Button>
              <Button size="1" variant="ghost" color="gray" onClick={() => { setTokenEntryOpen(false); setPersonalToken(''); }} disabled={working}>
                Cancel
              </Button>
            </Flex>
          )}
        </Flex>
      ) : (
        <Tooltip content={error ?? t(`${i18nPrefix}.unavailable`, { defaultValue: `${name} is not available yet. Ask your administrator for help.` })}>
          <Flex align="center" gap="2" px="2" py="1" style={{ color: 'var(--slate-9)' }}>
            {provider === 'superhuman'
              ? <MaterialIcon name="description" size={20} color="var(--slate-9)" />
              : <img src={`/icons/connectors/${provider === 'google-drive' ? 'drive' : provider === 'atlassian' ? 'atlassian' : provider}.svg`} width={20} height={20} alt="" />}
            <Text size="2">{name}</Text>
            <Text size="1" color="gray">
              {error
                ? t(`${i18nPrefix}.statusUnavailable`, { defaultValue: 'Unavailable' })
                : t(`${i18nPrefix}.unavailableShort`, { defaultValue: 'Unavailable' })}
            </Text>
            <MaterialIcon name="info" size={14} />
          </Flex>
        </Tooltip>
      )}
      {error && connection.configured && (
        <Box role="alert" style={{ position: 'absolute', top: 42, left: 16, zIndex: 30 }}>
          <Text size="1" color="red">{error}</Text>
        </Box>
      )}
    </Flex>
  );
}

export function SlackConnectionCard() {
  return <McpConnectionCard provider="slack" />;
}

export function NotionConnectionCard() {
  return <McpConnectionCard provider="notion" />;
}

export function MiroConnectionCard() {
  return <McpConnectionCard provider="miro" />;
}

export function JiraConnectionCard() {
  return <McpConnectionCard provider="atlassian" />;
}

export function GmailConnectionCard() {
  return <McpConnectionCard provider="gmail" />;
}

export function GoogleDriveConnectionCard() {
  return <McpConnectionCard provider="google-drive" />;
}

export function SuperhumanDocsConnectionCard() {
  return <McpConnectionCard provider="superhuman" />;
}

const CONFLUENCE_PERSONAL_TYPE = 'Confluence Data Center Personal';
const CONFLUENCE_BASE_URL = 'https://confluence.oddbytes.com';

export function ConfluenceConnectionCard() {
  const [instances, setInstances] = useState<Array<{
    _key?: string;
    type: string;
    scope?: string;
    authType?: string;
    isAuthenticated?: boolean;
  }>>([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    const result = await ConnectorsApi.getActiveConnectors('personal');
    const personalInstances = result.connectors.filter(
      (connector) => connector.type === CONFLUENCE_PERSONAL_TYPE && connector.scope === 'personal',
    );
    setInstances(personalInstances);
    return personalInstances;
  }, []);

  useEffect(() => {
    let active = true;
    void ConnectorsApi.getActiveConnectors('personal')
      .then(({ connectors }) => {
        if (active) {
          setInstances(connectors.filter(
            (connector) => connector.type === CONFLUENCE_PERSONAL_TYPE && connector.scope === 'personal',
          ));
        }
      })
      .catch(() => { if (active) setError('Could not check Confluence right now.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const connectedInstance = instances.find((instance) => instance.isAuthenticated);
  const hasSavedInstance = instances.length > 0;

  const connect = () => {
    setError(null);
    setFormOpen(true);
  };

  const saveCredentials = async () => {
    if (!username.trim() || !password || working) return;
    setWorking(true);
    setError(null);
    const auth = {
      baseUrl: CONFLUENCE_BASE_URL,
      username: username.trim(),
      password,
      connectorScope: 'personal',
    };
    try {
      const compatibleExisting = instances.find(
        (instance) => instance._key && instance.authType?.toUpperCase() === 'BASIC_AUTH',
      );
      let connectorId = compatibleExisting?._key;

      if (connectorId) {
        await ConnectorsApi.saveAuthConfig(connectorId, { auth, baseUrl: window.location.origin });
      } else {
        // Replacing a previous personal auth mode is scoped to the current user's
        // own connector instances returned by the personal connector API.
        for (const instance of instances) {
          if (instance._key) await ConnectorsApi.deleteConnectorInstance(instance._key);
        }
        const created = await ConnectorsApi.createConnectorInstance({
          connectorType: CONFLUENCE_PERSONAL_TYPE,
          instanceName: 'Confluence',
          scope: 'personal',
          authType: 'BASIC_AUTH',
          config: { auth },
          baseUrl: window.location.origin,
        }) as { connector?: { connectorId?: string }; connectorId?: string; _key?: string };
        connectorId = created.connector?.connectorId ?? created.connectorId ?? created._key;
      }

      if (!connectorId) throw new Error('The connector was saved without an instance ID.');
      await startConnectorSync({ _key: connectorId, type: CONFLUENCE_PERSONAL_TYPE });
      setUsername('');
      setPassword('');
      setFormOpen(false);
      await refreshStatus();
    } catch {
      setError('Could not connect Confluence. Check your username and password, then try again.');
      // A sync may fail after credentials were saved; reflect the saved connection.
      try { await refreshStatus(); } catch { /* keep the actionable connection error */ }
    } finally {
      setWorking(false);
    }
  };

  const disconnect = async () => {
    if (working) return;
    setWorking(true);
    setError(null);
    try {
      for (const instance of instances) {
        if (instance._key) await ConnectorsApi.deleteConnectorInstance(instance._key);
      }
      setInstances([]);
      setFormOpen(false);
    } catch {
      setError('Could not disconnect Confluence. Please try again.');
    } finally {
      setWorking(false);
    }
  };

  if (loading) return null;
  const connected = Boolean(connectedInstance);

  return (
    <Flex align="center" gap="2" style={{ minHeight: 36, flexShrink: 0 }} aria-label="Confluence connection">
      <Flex direction="column" align="stretch" gap="2" px="2" py="1" style={{ minHeight: 34, border: '1px solid var(--slate-5)', borderRadius: 'var(--radius-3)', background: 'var(--color-panel)' }}>
        <Flex align="center" gap="2">
          <img src="/icons/connectors/confluence.svg" width={20} height={20} alt="" />
          <Text size="2" weight="medium" style={{ color: 'var(--slate-12)' }}>Confluence</Text>
          {connected ? (
            <Flex align="center" gap="1" aria-label="Connected">
              <MaterialIcon name="check_circle" size={14} color="var(--jade-9)" />
              <Text size="1" color="gray">Connected</Text>
            </Flex>
          ) : (
            <Button size="1" variant="soft" onClick={connect} disabled={working}>
              {hasSavedInstance ? 'Reconnect' : 'Connect'}
            </Button>
          )}
          {connected && (
            <DropdownMenu.Root>
              <Tooltip content="Confluence options">
                <DropdownMenu.Trigger>
                  <IconButton size="1" variant="ghost" color="gray" aria-label="Confluence options">
                    <MaterialIcon name="more_vert" size={16} />
                  </IconButton>
                </DropdownMenu.Trigger>
              </Tooltip>
              <DropdownMenu.Content align="start" sideOffset={4}>
                <DropdownMenu.Item onSelect={connect}>Reconnect</DropdownMenu.Item>
                <DropdownMenu.Item color="red" onSelect={() => void disconnect()}>Disconnect</DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          )}
        </Flex>
        {formOpen && (
          <Flex align="center" gap="2" wrap="wrap">
            <TextField.Root size="1" aria-label="Username" placeholder="Username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} style={{ width: 150 }} />
            <TextField.Root size="1" type="password" aria-label="Password" placeholder="Password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} style={{ width: 150 }} />
            <Button size="1" variant="solid" onClick={() => void saveCredentials()} disabled={!username.trim() || !password || working}>{working ? 'Connecting…' : 'Connect'}</Button>
            <Button size="1" variant="ghost" color="gray" onClick={() => { setFormOpen(false); setUsername(''); setPassword(''); }} disabled={working}>Cancel</Button>
          </Flex>
        )}
        {error && <Text size="1" color="red" role="alert">{error}</Text>}
      </Flex>
    </Flex>
  );
}
