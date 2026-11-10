import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';
import type { ReactNode } from 'react';
import { SkillEditorPanel } from '../components/skill-editor-panel';
import { SkillsApi } from '../api';

const state = vi.hoisted(() => ({ isAdmin: true, close: vi.fn(), setSkills: vi.fn(), t: (key: string) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: state.t }) }));
vi.mock('@/lib/store/user-store', () => ({ useUserStore: () => state.isAdmin, selectIsAdmin: () => state.isAdmin }));
vi.mock('../store', () => ({ useSkillsStore: () => ({ editorOpen: true, editingSkillName: 'pptx', editorTab: 'content', closeEditor: state.close, setEditorTab: vi.fn(), setSkills: state.setSkills }) }));
vi.mock('../api', () => ({ SkillsApi: { getSkill: vi.fn(), updateSkill: vi.fn(), listSkills: vi.fn() }, isSkillConflictError: () => false }));
vi.mock('@/lib/store/toast-store', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }));
vi.mock('../components/markdown-editor', () => ({ MarkdownEditor: ({ value, editable, onChange }: { value: string; editable: boolean; onChange: (value: string) => void }) => <textarea aria-label="Skill content" value={value} disabled={!editable} onChange={(e) => onChange(e.target.value)} /> }));
vi.mock('../../../components', () => ({
  WorkspaceRightPanel: ({ children, hideFooter, onPrimaryClick }: { children: ReactNode; hideFooter: boolean; onPrimaryClick: () => void }) => <div>{children}{!hideFooter && <button onClick={onPrimaryClick}>Save</button>}</div>,
  FormField: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TagInput: () => null, ConfirmationDialog: () => null, DestructiveTypedConfirmationDialog: () => null, SettingsRow: () => null,
}));
vi.mock('../../../components/workspace-right-panel', () => ({ useWorkspaceDrawerNestedModalHost: () => null }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const builtin = {
  name: 'pptx', description: 'Presentations', body: 'Old instructions', source: 'builtin', status: 'active',
  version: '1.0.0', category: null, subcategory: null, tags: [], license: null, compatibility: null,
  allowedTools: null, related: [], requires: [], concepts: [], updatedAt: '123', resources: {},
};

describe('built-in skill editor', () => {
  it('lets an admin edit and save a built-in skill', async () => {
    state.isAdmin = true;
    vi.mocked(SkillsApi.getSkill).mockResolvedValue(builtin as never);
    vi.mocked(SkillsApi.updateSkill).mockResolvedValue({} as never);
    vi.mocked(SkillsApi.listSkills).mockResolvedValue([]);
    render(<Theme><SkillEditorPanel /></Theme>);
    const editor = await screen.findByLabelText('Skill content') as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe('Old instructions'));
    expect(editor.disabled).toBe(false);
    fireEvent.change(editor, { target: { value: 'Updated instructions' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(SkillsApi.updateSkill).toHaveBeenCalledWith('pptx', expect.objectContaining({ body: 'Updated instructions' }), '123'));
  });

  it('keeps a built-in read-only for non-admins', async () => {
    state.isAdmin = false;
    vi.mocked(SkillsApi.getSkill).mockResolvedValue(builtin as never);
    render(<Theme><SkillEditorPanel /></Theme>);
    const editor = await screen.findByLabelText('Skill content') as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe('Old instructions'));
    expect(editor.disabled).toBe(true);
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
  });
});
