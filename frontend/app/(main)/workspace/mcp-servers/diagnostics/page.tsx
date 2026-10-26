'use client';

import { useCallback, useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { Box, Button, Flex, Heading, Text } from '@radix-ui/themes';
import { useRouter } from 'next/navigation';
import { McpServersApi } from '../api';
import type { McpRetrievalTraceResponse, McpTraceEvent, McpTraceRun } from '../types';
import {
  selectFeatureFlagsLoaded,
  selectMcpEnabled,
  selectMcpRetrievalTraceEnabled,
  useFeatureFlagsStore,
} from '@/lib/store/feature-flags-store';
import { selectIsAdmin, selectIsProfileInitialized, useUserStore } from '@/lib/store/user-store';

const panelStyle: CSSProperties = {
  border: '1px solid var(--gray-a6)',
  borderRadius: 10,
  background: 'var(--gray-a2)',
  padding: 16,
  minWidth: 0,
};

function timestampRange(event: McpTraceEvent) {
  const response = event.response;
  if (!response?.oldestTimestamp && !response?.newestTimestamp) return 'Not returned';
  if (response.oldestTimestamp === response.newestTimestamp) return response.oldestTimestamp;
  return `${response.oldestTimestamp ?? 'Unknown'} — ${response.newestTimestamp ?? 'Unknown'}`;
}

function McpTraceRunComparison({ run }: { run: McpTraceRun }) {
  const events = run.events ?? [];
  const discoveries = events.filter((event) => event.eventType === 'discovery');
  const invocations = events.filter((event) => event.eventType === 'invocation');

  return (
    <Box style={panelStyle} data-testid={`mcp-trace-run-${run.runId}`}>
      <Heading size="4" mb="2">Run {run.runId}</Heading>
      <Text as="p" size="2" color="gray">User: {run.userId}</Text>
      <Text as="p" size="2" color="gray">Effective user: {run.effectiveUserId}</Text>
      <Text as="p" size="2" color="gray">Conversation: {run.conversationId || '—'}</Text>
      <Text as="p" size="2" color="gray">Started: {run.startedAt}</Text>

      <Heading size="3" mt="4" mb="2">Tool discovery</Heading>
      {discoveries.length === 0 ? <Text color="gray" size="2">No discovery events.</Text> : discoveries.map((event) => (
        <Box key={event.eventId} style={{ ...panelStyle, marginBottom: 10 }}>
          <Text as="p" weight="bold">{event.serverName || event.instanceId}</Text>
          <Text as="p" size="2">Instance: {event.instanceId} · {event.transport || 'Unknown transport'} · {event.authMode || 'Unknown auth'}</Text>
          <Text as="p" size="2">Credential owner: {event.credentialOwnerId || '—'} · Present: {event.credentialExists ? 'Yes' : 'No'}</Text>
          <Text as="p" size="2">OAuth scopes: {event.credentialScopes?.join(', ') || 'None reported'}</Text>
          <Text as="p" size="2">Credential expiry: {event.credentialExpiresAt || 'Not reported'}</Text>
          <Text as="p" size="2">Outcome: {event.outcome || 'Unknown'}{event.errorClass ? ` (${event.errorClass})` : ''} · {event.durationMs ?? 0} ms</Text>
          <Text as="p" size="2" weight="medium" mt="2">Tools and schema fingerprints</Text>
          {(event.tools ?? []).length === 0 ? <Text as="p" size="2" color="gray">No tools discovered.</Text> : (
            <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
              {event.tools?.map((tool) => (
                <li key={`${tool.name}-${tool.schemaFingerprint}`}>
                  <Text size="2">{tool.name} · {tool.schemaFingerprint}</Text>
                </li>
              ))}
            </ul>
          )}
        </Box>
      ))}

      <Heading size="3" mt="4" mb="2">Tool invocations</Heading>
      {invocations.length === 0 ? <Text color="gray" size="2">No invocation events.</Text> : invocations.map((event) => (
        <Box key={event.eventId} style={{ ...panelStyle, marginBottom: 10 }}>
          <Text as="p" weight="bold">{event.toolName || 'Unknown tool'}</Text>
          <Text as="p" size="2">{event.serverName || event.instanceId} · {event.instanceId}</Text>
          <Text as="p" size="2">Outcome: {event.outcome || 'Unknown'}{event.error?.class ? ` (${event.error.class}${event.error.code ? `: ${event.error.code}` : ''})` : ''} · {event.durationMs ?? 0} ms</Text>
          <Text as="p" size="2" weight="medium" mt="2">Safe arguments</Text>
          <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: '4px 0', fontSize: 12 }}>
            {JSON.stringify(event.arguments ?? {}, null, 2)}
          </pre>
          <Text as="p" size="2">Result count: {event.response?.resultCount ?? 0}</Text>
          <Text as="p" size="2">Timestamp range: {timestampRange(event)}</Text>
          <Text as="p" size="2">Returned IDs: {JSON.stringify(event.response?.returnedIds ?? [])}</Text>
          <Text as="p" size="2">Paginated: {event.response?.paginated ? 'Yes' : 'No'} · Truncated: {event.response?.truncated ? 'Yes' : 'No'}</Text>
          {event.response?.sourceMetadata && <Text as="p" size="2">Result type/source: {event.response.sourceMetadata}</Text>}
        </Box>
      ))}
    </Box>
  );
}

export default function McpDiagnosticsPage() {
  const router = useRouter();
  const isAdmin = useUserStore(selectIsAdmin);
  const profileInitialized = useUserStore(selectIsProfileInitialized);
  const flagsLoaded = useFeatureFlagsStore(selectFeatureFlagsLoaded);
  const mcpEnabled = useFeatureFlagsStore(selectMcpEnabled);
  const traceEnabled = useFeatureFlagsStore(selectMcpRetrievalTraceEnabled);
  const [runs, setRuns] = useState<McpTraceRun[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<McpTraceRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);

  useEffect(() => {
    if (profileInitialized && isAdmin === false) router.replace('/workspace/general/');
  }, [profileInitialized, isAdmin, router]);

  useEffect(() => {
    if (flagsLoaded && !mcpEnabled) router.replace('/workspace/general/');
  }, [flagsLoaded, mcpEnabled, router]);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response: McpRetrievalTraceResponse = await McpServersApi.getMcpRetrievalTraces();
      setRuns(response.runs);
      setTruncated(response.truncated);
    } catch {
      setError('Could not load MCP diagnostic runs. Check MCP service and trace storage logs.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (profileInitialized && isAdmin && flagsLoaded && mcpEnabled && traceEnabled) void loadRuns();
  }, [profileInitialized, isAdmin, flagsLoaded, mcpEnabled, traceEnabled, loadRuns]);

  const toggleRun = (runId: string) => {
    setSelectedRunIds((current) => {
      if (current.includes(runId)) return current.filter((id) => id !== runId);
      if (current.length >= 2) return current;
      return [...current, runId];
    });
  };

  const compareRuns = async () => {
    if (selectedRunIds.length !== 2) return;
    setCompareLoading(true);
    setError(null);
    try {
      const response = await McpServersApi.getMcpRetrievalTraces(selectedRunIds);
      setComparison(response.runs);
      setTruncated(response.truncated);
    } catch {
      setError('Could not load the selected diagnostic runs. They may have expired.');
      setComparison([]);
    } finally {
      setCompareLoading(false);
    }
  };

  if (!profileInitialized || isAdmin === null || !flagsLoaded) {
    return <Flex p="6" justify="center"><Text color="gray">Loading workspace access…</Text></Flex>;
  }
  if (!isAdmin) return null;
  if (!mcpEnabled) return null;

  return (
    <Box p={{ initial: '4', md: '6' }}>
      <Heading size="7" mb="2">MCP Diagnostics</Heading>
      <Text as="p" color="gray" mb="5">Compare recent MCP tool discovery and retrieval metadata across runs. Message content and raw tool responses are excluded.</Text>

      {!traceEnabled ? (
        <Box style={panelStyle}>
          <Text as="p" weight="bold">Tracing is disabled</Text>
          <Text as="p" color="gray">An administrator can enable “Enable MCP Retrieval Traces” in Workspace → Labs. Runs are retained for seven days.</Text>
        </Box>
      ) : (
        <Flex direction="column" gap="5">
          <Box style={panelStyle}>
            <Flex justify="between" align="center" mb="3" gap="3" wrap="wrap">
              <Box>
                <Heading size="4">Recent runs</Heading>
                <Text size="2" color="gray">Select two runs to compare. Up to 200 recent runs are listed.</Text>
              </Box>
              <Button variant="soft" onClick={() => void loadRuns()} disabled={loading}>
                {loading ? 'Refreshing…' : 'Refresh'}
              </Button>
            </Flex>
            {loading && runs.length === 0 ? <Text color="gray">Loading runs…</Text> : null}
            {!loading && runs.length === 0 ? <Text color="gray">No recent MCP trace runs found.</Text> : null}
            <Flex direction="column" gap="2">
              {runs.map((run) => (
                <label key={`${run.runId}-${run.traceId}`} style={{ ...panelStyle, display: 'flex', alignItems: 'center', gap: 12, cursor: 'pointer', padding: 12 }}>
                  <input
                    type="checkbox"
                    checked={selectedRunIds.includes(run.runId)}
                    disabled={!selectedRunIds.includes(run.runId) && selectedRunIds.length >= 2}
                    onChange={() => toggleRun(run.runId)}
                    aria-label={`Select run ${run.runId}`}
                  />
                  <span style={{ minWidth: 0 }}>
                    <Text as="span" weight="medium">{run.runId}</Text>
                    <Text as="span" size="2" color="gray"> · {run.userId} · {run.startedAt}</Text>
                  </span>
                </label>
              ))}
            </Flex>
            {truncated && <Text as="p" size="2" color="gray" mt="2">Showing the latest 200 runs.</Text>}
            <Button mt="4" onClick={() => void compareRuns()} disabled={selectedRunIds.length !== 2 || compareLoading}>
              {compareLoading ? 'Loading comparison…' : 'Compare selected runs'}
            </Button>
          </Box>

          {error && <Text color="red">{error}</Text>}
          {comparison.length > 0 && (
            <Flex gap="4" align="start" wrap="wrap">
              {comparison.map((run) => (
                <Box key={`${run.runId}-${run.traceId}`} style={{ flex: '1 1 420px', minWidth: 0 }}>
                  <McpTraceRunComparison run={run} />
                </Box>
              ))}
            </Flex>
          )}
        </Flex>
      )}
    </Box>
  );
}
