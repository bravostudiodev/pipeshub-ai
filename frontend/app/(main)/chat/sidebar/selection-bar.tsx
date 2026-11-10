'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { AlertDialog, Button, Flex, Text } from '@radix-ui/themes';
import { useTranslation } from 'react-i18next';
import { buildChatHref } from '@/chat/build-chat-url';
import { ChatApi } from '@/chat/api';
import { AgentsApi } from '@/app/(main)/agents/api';
import { useChatStore, isConversationStreamingInScope } from '@/chat/store';
import { selectIdsForScope, useSidebarSelectionStore } from './selection-store';

const BULK_DELETE_CONCURRENCY = 4;

interface SelectionBarProps {
  scope: string;
  agentId?: string;
  /** Ids currently listed in the section; selected ids that have since disappeared are ignored. */
  visibleIds: string[];
}

/**
 * Appears under a chat list once any chat is selected and deletes the selection in one go.
 */
export function SelectionBar({ scope, agentId, visibleIds }: SelectionBarProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const ids = useSidebarSelectionStore(selectIdsForScope(scope));
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(
    () => () => {
      const state = useSidebarSelectionStore.getState();
      if (state.scope === scope) state.clear();
    },
    [scope],
  );

  const selected = useMemo(() => visibleIds.filter((id) => ids.has(id)), [visibleIds, ids]);
  const hasSelection = selected.length > 0;

  useEffect(() => {
    if (!hasSelection) setNotice(null);
  }, [hasSelection]);

  if (!hasSelection) return null;

  const handleDelete = async () => {
    setDeleting(true);
    setNotice(null);
    const chat = useChatStore.getState();
    const streaming = selected.filter((id) =>
      isConversationStreamingInScope(chat.slots, id, agentId ?? null),
    );
    const queue = selected.filter((id) => !streaming.includes(id));
    const deleted: string[] = [];
    let failed = 0;

    const worker = async () => {
      for (let id = queue.shift(); id; id = queue.shift()) {
        try {
          if (agentId) await AgentsApi.deleteAgentConversation(agentId, id);
          else await ChatApi.deleteConversation(id);
          deleted.push(id);
        } catch {
          failed += 1;
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(BULK_DELETE_CONCURRENCY, queue.length) }, worker));

    deleted.forEach((id) => chat.removeConversation(id));
    chat.bumpConversationsVersion();
    useSidebarSelectionStore.getState().remove(deleted);

    const openId = searchParams?.get('conversationId') ?? null;
    if (openId && deleted.includes(openId)) {
      const found = chat.getSlotByConvId(openId, { forAgentId: agentId ?? null });
      if (found) chat.evictSlot(found.slotId);
      else chat.clearActiveSlot();
      router.replace(agentId ? buildChatHref({ agentId }) : '/chat/');
    }

    setDeleting(false);
    setConfirmOpen(false);
    if (failed > 0 || streaming.length > 0) {
      setNotice(
        t('chat.selection.partial', {
          defaultValue: "Some chats couldn't be deleted ({{count}} left selected).",
          count: failed + streaming.length,
        }),
      );
    }
  };

  const handleCancel = () => {
    setNotice(null);
    useSidebarSelectionStore.getState().clear();
  };

  return (
    <Flex
      direction="column"
      gap="2"
      style={{
        flexShrink: 0,
        padding: 'var(--space-2) var(--space-3)',
        borderTop: '1px solid var(--slate-5)',
      }}
    >
      {notice && (
        <Text size="1" color="red" role="alert">
          {notice}
        </Text>
      )}
      <Flex align="center" justify="between" gap="2">
        <Text size="2" weight="medium" style={{ color: 'var(--slate-12)' }}>
          {t('chat.selection.count', { defaultValue: '{{count}} selected', count: selected.length })}
        </Text>
        <Flex gap="2">
          <Button size="1" variant="soft" color="gray" onClick={handleCancel} disabled={deleting}>
            {t('action.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button size="1" color="red" onClick={() => setConfirmOpen(true)} disabled={deleting}>
            {t('action.delete', { defaultValue: 'Delete' })}
          </Button>
        </Flex>
      </Flex>

      <AlertDialog.Root open={confirmOpen} onOpenChange={(open) => !deleting && setConfirmOpen(open)}>
        <AlertDialog.Content maxWidth="420px">
          <AlertDialog.Title>
            {t('chat.selection.confirmTitle', {
              defaultValue: 'Delete {{count}} chats?',
              count: selected.length,
            })}
          </AlertDialog.Title>
          <AlertDialog.Description size="2">
            {t('chat.selection.confirmDescription', {
              defaultValue: 'These chats will be permanently removed from OddJeeves.',
            })}
          </AlertDialog.Description>
          <Flex gap="3" mt="4" justify="end">
            <Button variant="soft" color="gray" onClick={() => setConfirmOpen(false)} disabled={deleting}>
              {t('action.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button color="red" onClick={() => void handleDelete()} loading={deleting}>
              {t('action.delete', { defaultValue: 'Delete' })}
            </Button>
          </Flex>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </Flex>
  );
}
