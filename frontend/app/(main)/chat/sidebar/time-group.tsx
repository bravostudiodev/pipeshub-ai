'use client';

import { useState } from 'react';
import { Checkbox, Flex } from '@radix-ui/themes';
import { useTranslation } from 'react-i18next';
import { ChatSectionElement, GeneratingTitleItem } from './chat-section-element';
import { ELEMENT_HEIGHT } from '@/app/components/sidebar';
import { selectIdsForScope, selectionScopeFor, useSidebarSelectionStore } from './selection-store';
import type { PendingConversation } from '@/chat/store';
import {
  groupByTime,
  getNonEmptyGroups as getNonEmptyGroupsGeneric,
  TIME_GROUP_KEYS,
  type TimeGroupKey,
} from '@/lib/utils/group-by-time';
import { getConversationLastActivityMs } from '@/lib/utils/conversation-activity';
import type { Conversation } from '@/chat/types';

// Re-export for consumers that still import from here
export { TIME_GROUP_KEYS, type TimeGroupKey };

/** Maps the fixed TimeGroupKey to its i18n translation key */
const TIME_GROUP_I18N: Record<TimeGroupKey, string> = {
  'Today': 'timeGroup.today',
  'Yesterday': 'timeGroup.yesterday',
  'Previous 7 Days': 'timeGroup.previous7Days',
  'Older': 'timeGroup.older',
};

/**
 * Groups conversations into time buckets.
 * Delegates to the shared `groupByTime` utility.
 */
export function groupConversationsByTime(
  conversations: Conversation[]
): Record<TimeGroupKey, Conversation[]> {
  return groupByTime(conversations, (conv) => getConversationLastActivityMs(conv));
}

/**
 * Returns only the non-empty group entries in display order.
 */
export function getNonEmptyGroups(
  groups: Record<TimeGroupKey, Conversation[]>
): Array<[TimeGroupKey, Conversation[]]> {
  return getNonEmptyGroupsGeneric(groups, getConversationLastActivityMs);
}

// ========================================
// Components
// ========================================

interface TimeGroupProps {
  label: TimeGroupKey;
  conversations: Conversation[];
  currentConversationId: string | null;
  onSelectConversation: (id: string) => void;
  /** Pending conversations to show as clickable "Generating Title…" shimmers */
  pendingConversations?: PendingConversation[];
  /** Agent sidebar: use agent delete API and hide rename/archive on rows */
  agentId?: string;
}

/**
 * TimeGroup — renders a time-period sub-heading ("Today", "Yesterday", …)
 * followed by the list of chat items in that period.
 */
export function TimeGroup({
  label,
  conversations,
  currentConversationId,
  onSelectConversation,
  pendingConversations = [],
  agentId,
}: TimeGroupProps) {
  const { t } = useTranslation();
  const pendingSortedNewestFirst = [...pendingConversations].sort(
    (a, b) => b.createdAt - a.createdAt
  );
  const scope = selectionScopeFor(agentId);
  const selectedIds = useSidebarSelectionStore(selectIdsForScope(scope));
  const setMany = useSidebarSelectionStore((s) => s.setMany);
  const [headerHovered, setHeaderHovered] = useState(false);
  const selectableIds = conversations.filter((c) => c.isOwner === true).map((c) => c.id);
  const selectedCount = selectableIds.filter((id) => selectedIds.has(id)).length;
  const allSelected = selectableIds.length > 0 && selectedCount === selectableIds.length;
  const groupLabel = t(TIME_GROUP_I18N[label]);
  return (
    <Flex direction="column">
      {/* Sub-heading */}
      <Flex
        align="center"
        justify="between"
        onMouseEnter={() => setHeaderHovered(true)}
        onMouseLeave={() => setHeaderHovered(false)}
        style={{
          height: ELEMENT_HEIGHT,
          padding: '0 var(--space-3)',
        }}
      >
        <span
          style={{
            fontSize: 12,
            fontWeight: 400,
            lineHeight: 'var(--line-height-1)',
            letterSpacing: '0.04px',
            color: 'var(--slate-10)',
          }}
        >
          {groupLabel}
        </span>
        {selectableIds.length > 0 && (
          <Checkbox
            size="1"
            checked={allSelected ? true : selectedCount > 0 ? 'indeterminate' : false}
            onCheckedChange={() => setMany(scope, selectableIds, !allSelected)}
            aria-label={t('chat.selection.selectGroup', {
              defaultValue: 'Select all chats in {{group}}',
              group: groupLabel,
            })}
            style={{ opacity: headerHovered || selectedCount > 0 ? 1 : 0.45, transition: 'opacity 0.15s ease' }}
          />
        )}
      </Flex>

      {/* Chat items */}
      <Flex direction="column" gap="1">
        {pendingSortedNewestFirst.map((pending) => (
          <GeneratingTitleItem key={pending.slotId} slotId={pending.slotId} />
        ))}
        {conversations.map((conv) => (
          <ChatSectionElement
            key={conv.id}
            conversation={conv}
            isActive={currentConversationId === conv.id}
            onClick={() => onSelectConversation(conv.id)}
            agentId={agentId}
            selectionScope={scope}
          />
        ))}
      </Flex>
    </Flex>
  );
}
