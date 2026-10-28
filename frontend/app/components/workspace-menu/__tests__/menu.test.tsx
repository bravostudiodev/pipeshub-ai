import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { WorkspaceMenu } from '../menu';

vi.mock('@/config', () => ({
  logoutFromWorkspaceMenu: vi.fn(),
  SettingsSection: () => <div>Workspace Settings</div>,
}));
vi.mock('@/app/components/ui/user-avatar', () => ({ UserAvatar: () => null }));
vi.mock('../appearance-panel', () => ({ AppearancePanel: () => null }));
vi.mock('../language-panel', () => ({ LanguagePanel: () => null }));

afterEach(cleanup);

describe('workspace menu', () => {
  it('shows settings without the external documentation and GitHub links', () => {
    render(<WorkspaceMenu isOpen onClose={() => {}} org={null} />);
    expect(screen.getByText('Workspace Settings')).toBeTruthy();
    expect(screen.queryByText('Documentation')).toBeNull();
    expect(screen.queryByText(/GitHub/i)).toBeNull();
  });
});
