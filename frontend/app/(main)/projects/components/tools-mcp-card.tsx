'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Checkbox, Flex, Text } from '@radix-ui/themes';
import { useTranslation } from 'react-i18next';
import { MaterialIcon } from '@/app/components/ui/MaterialIcon';
import { ConnectorIcon, resolveConnectorType } from '@/app/components/ui/ConnectorIcon';
import { fetchToolCatalog } from '@/chat/hooks/use-project-scope-hydration';
import { bareToolFullName, resolveProjectToolKeys, type CatalogToolGroupRow } from '@/chat/tool-groups';
import { useFeatureFlagsStore, selectMcpEnabled } from '@/lib/store/feature-flags-store';
import { useAuthStore } from '@/lib/store/auth-store';
import { catalogIdentityFromToken, mcpCatalogRevision, MCP_CATALOG_CHANGED_EVENT } from '@/chat/mcp-catalog-refresh';

interface ToolGroupRow {
  key: string;
  label: string;
  /** Native bare names or instance-scoped MCP keys. */
  fullNames: string[];
  icon: React.ReactNode;
}

function toCardRows(groups: CatalogToolGroupRow[], kind: 'toolset' | 'mcp'): ToolGroupRow[] {
  return groups.map((g) => ({
    key: `${kind}:${g.instanceId}`,
    label: g.label,
    fullNames: Array.from(new Set(kind === 'mcp' ? g.fullNames : g.fullNames.map(bareToolFullName))),
    icon:
      kind === 'mcp' ? (
        <MaterialIcon name="hub" size={16} color="var(--gray-11)" />
      ) : (
        <ConnectorIcon type={resolveConnectorType(g.toolsetSlug || g.label)} size={16} />
      ),
  }));
}

interface ToolsMcpCardProps {
  selectedTools: string[];
  canEdit: boolean;
  onChange: (tools: string[]) => void;
}

/**
 * Project Tools & MCP picker over the same catalog the composer uses
 * (`fetchToolCatalog`). Persists exact instance-scoped MCP selections;
 * native toolset keys remain bare for backward compatibility.
 */
export function ToolsMcpCard({ selectedTools, canEdit, onChange }: ToolsMcpCardProps) {
  const { t } = useTranslation();
  const mcpEnabled = useFeatureFlagsStore(selectMcpEnabled);
  const identity = useAuthStore((s) => catalogIdentityFromToken(s.accessToken));
  const [revision, setRevision] = useState(mcpCatalogRevision);
  const [groups, setGroups] = useState<ToolGroupRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    const changed = () => setRevision(mcpCatalogRevision());
    window.addEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
    return () => window.removeEventListener(MCP_CATALOG_CHANGED_EVENT, changed);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setGroups([]);
    async function load() {
      setIsLoading(true);
      setLoadError(false);
      try {
        const catalog = await fetchToolCatalog(mcpEnabled);
        if (cancelled) return;
        setGroups([...toCardRows(catalog.toolGroups, 'toolset'), ...toCardRows(catalog.mcpGroups, 'mcp')]);
      } catch {
        if (!cancelled) setLoadError(true);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [mcpEnabled, identity, revision]);

  // Bare legacy MCP grants map only to the first instance, not every
  // same-name server. Any edit persists the explicit instance-scoped keys.
  const selectedSet = useMemo(() => resolveProjectToolKeys(
    selectedTools,
    groups.filter((g) => g.key.startsWith('mcp:')).map((g) => ({
      instanceId: g.key.slice(4), fullNames: g.fullNames,
    }))
  ).keys, [selectedTools, groups]);

  const groupCheckState = useCallback(
    (fullNames: string[]): boolean | 'indeterminate' => {
      const on = fullNames.filter((fn) => selectedSet.has(fn)).length;
      if (on === 0) return false;
      if (on === fullNames.length) return true;
      return 'indeterminate';
    },
    [selectedSet],
  );

  const toggleGroup = useCallback(
    (fullNames: string[], enabled: boolean) => {
      const next = new Set(selectedSet);
      fullNames.forEach((fn) => (enabled ? next.add(fn) : next.delete(fn)));
      onChange(Array.from(next));
    },
    [selectedSet, onChange],
  );

  if (isLoading) {
    return (
      <Text size="2" style={{ color: 'var(--slate-10)' }}>
        {t('common.loading', { defaultValue: 'Loading…' })}
      </Text>
    );
  }
  if (loadError) {
    return (
      <Text size="2" style={{ color: '#ef4444' }}>
        {t('chat.projects.workspace.failedToLoad')}
      </Text>
    );
  }
  if (groups.length === 0) {
    return (
      <Text size="2" style={{ color: 'var(--slate-10)' }}>
        {t('chat.projects.workspace.noToolsAvailable', {
          defaultValue: 'No authenticated actions or MCP servers to add yet.',
        })}
      </Text>
    );
  }

  return (
    <Flex direction="column" gap="1">
      {groups.map((group) => {
        const checkState = groupCheckState(group.fullNames);
        return (
          <Flex
            key={group.key}
            align="center"
            gap="2"
            style={{
              padding: 'var(--space-2)',
              borderRadius: 'var(--radius-2)',
              background: 'var(--olive-1)',
              cursor: canEdit ? 'pointer' : 'default',
            }}
            onClick={() => canEdit && toggleGroup(group.fullNames, checkState !== true)}
          >
            <span style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
              <Checkbox
                size="1"
                checked={checkState}
                disabled={!canEdit}
                onCheckedChange={(v) => toggleGroup(group.fullNames, v === true)}
                onClick={(e) => e.stopPropagation()}
              />
            </span>
            {group.icon}
            <Text
              size="2"
              style={{
                color: 'var(--slate-12)',
                flex: 1,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              truncate
            >
              {group.label}
            </Text>
            <Text size="1" style={{ color: 'var(--slate-10)', flexShrink: 0 }}>
              {group.fullNames.filter((fn) => selectedSet.has(fn)).length}/{group.fullNames.length}
            </Text>
          </Flex>
        );
      })}
    </Flex>
  );
}
