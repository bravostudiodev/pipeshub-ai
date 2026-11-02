'use client';

import { useCallback, useEffect, useState } from 'react';
import { Button, Dialog, Flex, IconButton, Text, TextField } from '@radix-ui/themes';
import { apiClient } from '@/lib/api';

interface Share { _id: string; version: number; expiresAt: string }

export function ArtifactShareDialog({ artifactId, version, neutral = false }: { artifactId: string; version: number; neutral?: boolean }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState('7');
  const [shares, setShares] = useState<Share[]>([]);
  const [link, setLink] = useState('');
  const [linkId, setLinkId] = useState('');
  const [expires, setExpires] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const base = `/api/v1/artifacts/${encodeURIComponent(artifactId)}/shares`;

  const refresh = useCallback(async () => {
    const response = await apiClient.get<{ shares: Share[] }>(base);
    setShares(response.data.shares);
  }, [base]);

  useEffect(() => {
    if (!open) { setLink(''); setLinkId(''); setMessage(''); return; }
    void refresh().catch(() => setMessage('Could not load active shares.'));
  }, [open, refresh]);

  async function create() {
    setBusy(true); setMessage('');
    try {
      const response = await apiClient.post<{ id: string; token: string; expiresAt: string }>(base, {
        version, expiresInDays: Number(days),
      });
      setLink(`${window.location.origin}/share/${encodeURIComponent(response.data.token)}`);
      setLinkId(response.data.id);
      setExpires(response.data.expiresAt);
      try { await refresh(); } catch { setMessage('Link created, but active shares could not be refreshed.'); }
    } catch { setMessage('Could not create the share. Only the artifact owner can share it.'); }
    finally { setBusy(false); }
  }

  async function revoke(id: string) {
    setBusy(true); setMessage('');
    try {
      await apiClient.delete(`${base}/${encodeURIComponent(id)}`);
      if (linkId === id) { setLink(''); setLinkId(''); }
      setShares((current) => current.filter((share) => share._id !== id));
      try { await refresh(); } catch { setMessage('Sharing stopped, but the list could not be refreshed.'); }
    } catch { setMessage('Could not stop sharing.'); }
    finally { setBusy(false); }
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger><IconButton size="1" variant="ghost" color={neutral ? 'gray' : undefined} aria-label="Share artifact" title="Share artifact"><span className="material-icons-outlined" style={{ fontSize: 18 }}>share</span></IconButton></Dialog.Trigger>
      <Dialog.Content className="artifact-share-dialog" maxWidth="500px">
        <Dialog.Title>Share artifact</Dialog.Title>
        <Dialog.Description size="2">Anyone who can access this link can view this artifact. The link can be forwarded, and the artifact may contain sensitive information.</Dialog.Description>
        <Flex direction="column" gap="3" style={{ marginTop: 'var(--space-4)' }}>
          <Text size="2">Sharing version {version}</Text>
          <Flex asChild align="center" gap="3">
            <label>
              <Text size="2">Expires after</Text>
              <select
                aria-label="Expiration"
                value={days}
                onChange={(event) => setDays(event.target.value)}
                style={{ padding: 'var(--space-2)', border: '1px solid var(--gray-7)', borderRadius: 'var(--radius-2)', background: 'var(--color-panel-solid)', color: 'var(--gray-12)', font: 'inherit', cursor: 'pointer' }}
              >
                <option value="1">1 day</option>
                <option value="7">7 days</option>
                <option value="30">30 days</option>
              </select>
            </label>
          </Flex>
          <Button onClick={create} disabled={busy}>Create link</Button>
          {link && <Flex direction="column" gap="2"><Text size="2">Expires {new Date(expires).toLocaleString()}. Copy this link now; it cannot be shown again.</Text><TextField.Root aria-label="Share link" value={link} readOnly /><Button variant="soft" onClick={() => { void navigator.clipboard.writeText(link).then(() => setMessage('Link copied.')).catch(() => setMessage('Could not copy link.')); }}>Copy link</Button></Flex>}
          {shares.map((share) => <Flex key={share._id} align="center" justify="between" gap="2"><Text size="2">Version {share.version} · expires {new Date(share.expiresAt).toLocaleString()}</Text><Button variant="soft" color="red" disabled={busy} onClick={() => revoke(share._id)}>Stop sharing</Button></Flex>)}
          <Text size="1" color="gray">Stopping sharing cannot remove copies already downloaded.</Text>
          {message && <Text size="2" role="status">{message}</Text>}
          <Dialog.Close><Button variant="soft">Close</Button></Dialog.Close>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
