import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';
import { McpServersApi } from '@/app/(main)/workspace/mcp-servers/api';
import { ConnectorsApi } from '@/app/(main)/workspace/connectors/api';
import { startConnectorSync } from '@/app/(main)/workspace/connectors/utils/connector-sync-actions';
import {
  JiraConnectionCard,
  MiroConnectionCard,
  GmailConnectionCard,
  GoogleDriveConnectionCard,
  SlackConnectionCard,
  SuperhumanDocsConnectionCard,
  ConfluenceConnectionCard,
} from '../slack-connection-card';

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => undefined },
  useTranslation: () => ({ t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key }),
}));

vi.mock('@/app/(main)/workspace/mcp-servers/api', () => ({
  McpServersApi: {
    getSlackConnection: vi.fn(),
    getMiroConnection: vi.fn(),
    getAtlassianConnection: vi.fn(),
    getGmailConnection: vi.fn(),
    getGoogleDriveConnection: vi.fn(),
    getSuperhumanDocsConnection: vi.fn(),
    authenticate: vi.fn(),
    removeCredentials: vi.fn(),
  },
}));

vi.mock('@/app/(main)/workspace/connectors/api', () => ({
  ConnectorsApi: {
    getActiveConnectors: vi.fn(),
    createConnectorInstance: vi.fn(),
    saveAuthConfig: vi.fn(),
    deleteConnectorInstance: vi.fn(),
  },
}));

vi.mock('@/app/(main)/workspace/connectors/utils/connector-sync-actions', () => ({
  startConnectorSync: vi.fn(),
}));

vi.mock('@/app/(main)/workspace/mcp-servers/hooks/use-mcp-oauth-popup', () => ({
  useMcpOAuthPopup: () => ({ startOAuthPopup: vi.fn(), status: 'idle' }),
}));

const getStatus = vi.mocked(McpServersApi.getSlackConnection);
const getMiroStatus = vi.mocked(McpServersApi.getMiroConnection);
const getAtlassianStatus = vi.mocked(McpServersApi.getAtlassianConnection);
const getGmailStatus = vi.mocked(McpServersApi.getGmailConnection);
const getGoogleDriveStatus = vi.mocked(McpServersApi.getGoogleDriveConnection);
const getSuperhumanStatus = vi.mocked(McpServersApi.getSuperhumanDocsConnection);

function renderCard() {
  render(<Theme><SlackConnectionCard /></Theme>);
}

beforeEach(() => {
  getStatus.mockReset();
  getMiroStatus.mockReset();
  getAtlassianStatus.mockReset();
  getGmailStatus.mockReset();
  getGoogleDriveStatus.mockReset();
  getSuperhumanStatus.mockReset();
  vi.mocked(McpServersApi.authenticate).mockReset();
  vi.mocked(ConnectorsApi.getActiveConnectors).mockReset();
  vi.mocked(ConnectorsApi.createConnectorInstance).mockReset();
  vi.mocked(ConnectorsApi.saveAuthConfig).mockReset();
  vi.mocked(ConnectorsApi.deleteConnectorInstance).mockReset();
  vi.mocked(startConnectorSync).mockReset();
});

afterEach(() => cleanup());

describe('SlackConnectionCard', () => {
  it('offers a compact Connect action when the user has not connected', async () => {
    getStatus.mockResolvedValue({ configured: true, instanceId: 'shared-slack', isConnected: false });
    renderCard();

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    expect(screen.queryByText('Reconnect')).toBeNull();
  });

  it('uses Reconnect for a saved authorization that Slack has revoked', async () => {
    getStatus.mockResolvedValue({
      configured: true,
      instanceId: 'shared-slack',
      isConnected: false,
      hasCredentials: true,
    });
    renderCard();

    expect(await screen.findByRole('button', { name: 'Reconnect' })).toBeTruthy();
  });

  it('shows Connected as static status and provides a separate account options control', async () => {
    getStatus.mockResolvedValue({
      configured: true,
      instanceId: 'shared-slack',
      isConnected: true,
      hasCredentials: true,
    });
    renderCard();

    expect(await screen.findByText('Connected')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Reconnect' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Slack options' })).toBeTruthy();
  });

  it('shows a non-interactive unavailable state when the administrator has not configured Slack', async () => {
    getStatus.mockResolvedValue({ configured: false, isConnected: false });
    renderCard();

    await waitFor(() => expect(screen.getByText('Unavailable')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'Connect' })).toBeNull();
  });

  it('links Superhuman Docs users to the personal token guide beside Connect', async () => {
    getSuperhumanStatus.mockResolvedValue({ configured: true, instanceId: 'shared-superhuman', isConnected: false });
    render(<Theme><SuperhumanDocsConnectionCard /></Theme>);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    const guideLink = screen.getByRole('link', { name: 'How to get a token' });
    expect(guideLink.getAttribute('href')).toBe('/superhuman-guide');
  });

  it('shows Jira for the Atlassian Rovo connection', async () => {
    getAtlassianStatus.mockResolvedValue({ configured: true, instanceId: 'shared-atlassian', isConnected: false });
    render(<Theme><JiraConnectionCard /></Theme>);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    expect(screen.getByText('Jira')).toBeTruthy();
  });

  it('offers the standard OAuth connection action for Miro', async () => {
    getMiroStatus.mockResolvedValue({ configured: true, instanceId: 'org-miro', isConnected: false });
    render(<Theme><MiroConnectionCard /></Theme>);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
    expect(screen.getByText('Miro')).toBeTruthy();
  });

  it('creates and syncs the current user’s Confluence Data Center Personal connector', async () => {
    vi.mocked(ConnectorsApi.getActiveConnectors).mockResolvedValue({ success: true, connectors: [] });
    vi.mocked(ConnectorsApi.createConnectorInstance).mockResolvedValue({ connectorId: 'personal-confluence' });
    const { fireEvent } = await import('@testing-library/react');
    render(<Theme><ConfluenceConnectionCard /></Theme>);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Username' }), { target: { value: 'person@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'private-password' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Connect' })[1]);

    await waitFor(() => expect(ConnectorsApi.createConnectorInstance).toHaveBeenCalledWith({
      connectorType: 'Confluence Data Center Personal',
      instanceName: 'Confluence',
      scope: 'personal',
      authType: 'BASIC_AUTH',
      config: { auth: {
        baseUrl: 'https://confluence.oddbytes.com',
        username: 'person@example.com',
        password: 'private-password',
        connectorScope: 'personal',
      } },
      baseUrl: window.location.origin,
    }));
    expect(startConnectorSync).toHaveBeenCalledWith({ _key: 'personal-confluence', type: 'Confluence Data Center Personal' });
    expect(screen.queryByText('private-password')).toBeNull();
  });

  it('offers the same personal Connect action for Gmail', async () => {
    getGmailStatus.mockResolvedValue({ configured: true, instanceId: 'shared-gmail', isConnected: false });
    render(<Theme><GmailConnectionCard /></Theme>);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
  });

  it('offers the same personal Connect action for Google Drive', async () => {
    getGoogleDriveStatus.mockResolvedValue({ configured: true, instanceId: 'shared-drive', isConnected: false });
    render(<Theme><GoogleDriveConnectionCard /></Theme>);

    expect(await screen.findByRole('button', { name: 'Connect' })).toBeTruthy();
  });
});
