import type { SkillMetadata } from './types';

/** Built-ins are organization-wide; only administrators can edit them. */
export function canEditSkillContent(skill: Pick<SkillMetadata, 'source'>, isAdmin: boolean): boolean {
  return skill.source !== 'builtin' || isAdmin;
}

/** Whether the availability Switch should render for this skill.

Custom skills: the creator (the management list is already creator-scoped).
Builtin skills: org admins only. Deprecated/candidate skills stay one-way
lifecycle states — the Switch does not undeprecate. */
export function canToggleSkillAvailability(
  skill: Pick<SkillMetadata, 'source' | 'status'>,
  isAdmin: boolean,
): boolean {
  if (skill.status !== 'active' && skill.status !== 'disabled') {
    return false;
  }
  if (skill.source === 'builtin') {
    return isAdmin;
  }
  return true;
}
