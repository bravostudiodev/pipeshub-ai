'use client';

import React, { useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Flex, Text } from '@radix-ui/themes';
import { useTranslation } from 'react-i18next';
import { useChatStore, selectPendingForSidebar } from '@/chat/store';
import { useCommandStore } from '@/lib/store/command-store';
import { useMobileSidebarStore } from '@/lib/store/mobile-sidebar-store';
import { useIsMobile } from '@/lib/hooks/use-is-mobile';
import { debugLog } from '@/chat/debug-logger';
import { MaterialIcon } from '@/app/components/ui/MaterialIcon';
import { ChatSection } from './chat-section';
import { groupConversationsByTime, getNonEmptyGroups } from './time-group';

/**
 * Maximum number of chat items shown per section before
 * overflow triggers a "More" button. Chat-sidebar-specific.
 */
const MAX_VISIBLE_CHATS = 10;

/** Number of skeleton items shown while loading each section */
const YOUR_CHATS_SKELETON_COUNT = 3;

/**
 * Chat sections — renders time-grouped conversations
 * and an overflow "More" button.
 *
 * Wrapped in React.memo to prevent parent-cascade re-renders.
 */
export const ChatSections = React.memo(function ChatSections({
  onOpenMoreChats,
}: {
  onOpenMoreChats: (sectionType: 'shared' | 'your') => void;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentConversationId = searchParams?.get('conversationId') ?? null;
  const { t } = useTranslation();

  const conversations = useChatStore((s) => s.conversations);
  const isConversationsLoading = useChatStore((s) => s.isConversationsLoading);
  const conversationsError = useChatStore((s) => s.conversationsError);
  const pendingConversations = useChatStore((s) => s.pendingConversations);
  const slots = useChatStore((s) => s.slots);
  const pagination = useChatStore((s) => s.pagination);

  // ── Render-reason tracking ──────────────────────────────────────
  debugLog.tick('[sidebar] [ChatSections]');
  const prevChatSectionsRef = React.useRef<Record<string, unknown>>({});
  const currentSectionsVals: Record<string, unknown> = {
    currentConversationId, conversations,
    isConversationsLoading, conversationsError, pendingConversations, slots, pagination,
  };
  const sectionsReasons: string[] = [];
  for (const [k, v] of Object.entries(currentSectionsVals)) {
    // eslint-disable-next-line react-hooks/refs -- intentional: debug render-reason tracking
    if (!Object.is(v, prevChatSectionsRef.current[k])) sectionsReasons.push(k);
  }
  if (sectionsReasons.length > 0) {
    debugLog.reason('[sidebar] [ChatSections]', sectionsReasons);
  }
  // eslint-disable-next-line react-hooks/refs -- intentional: update previous-props snapshot for next render diff
  prevChatSectionsRef.current = currentSectionsVals;

  const dispatch = useCommandStore((s) => s.dispatch);
  const closeMobileSidebar = useMobileSidebarStore((s) => s.close);
  const isMobile = useIsMobile();

  const [recentsCollapsed, setRecentsCollapsed] = useState(true);

  const handleNewChat = () => {
    if (!dispatch('newChat')) router.push('/chat/');
  };
  const handleSelectConversation = () => {
    if (isMobile) closeMobileSidebar();
  };

  // Overflow detection — show "More" if there are more items than fit,
  // OR if the server indicated there are additional pages to fetch.
  const hasMoreYour =
    conversations.length > MAX_VISIBLE_CHATS ||
    (conversations.length > 0 && (pagination?.hasNextPage ?? false));

  // Slice for overflow limit
  const visibleYour = hasMoreYour
    ? conversations.slice(0, MAX_VISIBLE_CHATS)
    : conversations;

  // Time-group only "Your Chats"
  const yourTimeGroups = groupConversationsByTime(visibleYour);
  const yourNonEmptyGroups = getNonEmptyGroups(yourTimeGroups);

  const activePendingConversations = useMemo(() => {
    const convIds = new Set(conversations.map((c) => c.id));
    return selectPendingForSidebar(pendingConversations, slots, convIds, 'global');
  }, [pendingConversations, slots, conversations]);

  return (
    <Flex
      direction="column"
      gap="3"
      style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}
    >
      {/* Conversations — collapsible wrapper */}
      <Flex
        direction="column"
        style={recentsCollapsed ? undefined : { flex: 1, minHeight: 0, overflow: 'hidden' }}
      >
        {/* Conversations header with collapse toggle */}
        <Flex
          align="center"
          justify="between"
          onClick={() => setRecentsCollapsed((c) => !c)}
          style={{
            height: 32,
            padding: '0 var(--space-3)',
            flexShrink: 0,
            cursor: 'pointer',
            borderRadius: 'var(--radius-2)',
            userSelect: 'none',
          }}
        >
          <Text
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--slate-12)',
              lineHeight: 1,
            }}
          >
            {t('chat.recents')}
          </Text>
          <MaterialIcon
            name="chevron_right"
            size={16}
            color="var(--slate-11)"
            style={{
              transform: recentsCollapsed ? 'rotate(0deg)' : 'rotate(90deg)',
              transition: 'transform 0.2s ease',
              display: 'block',
            }}
          />
        </Flex>

        {!recentsCollapsed && (
          <Flex
            direction="column"
            gap="3"
            style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}
          >
            {/* Time-grouped chats; no section title since the wrapper is already "Conversations" */}
            <ChatSection
              timeGroups={yourNonEmptyGroups}
              isLoading={isConversationsLoading}
              hasError={!!conversationsError}
              currentConversationId={currentConversationId}
              onSelectConversation={handleSelectConversation}
              onNewChat={handleNewChat}
              skeletonCount={YOUR_CHATS_SKELETON_COUNT}
              isScrollable
              hasMore={hasMoreYour}
              onMore={() => onOpenMoreChats('your')}
              pendingConversations={activePendingConversations}
            />
          </Flex>
        )}
      </Flex>
    </Flex>
  );
});
