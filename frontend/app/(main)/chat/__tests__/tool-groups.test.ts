import { describe, expect, it } from 'vitest';
import { encodeToolSelectionForWire, resolveProjectToolKeys } from '../tool-groups';

describe('encodeToolSelectionForWire', () => {
  it('sends native toolset keys bare and MCP keys with their instance', () => {
    const groups = [{ fullNames: ['inst-a:mcp_notion_search'] }];
    expect(encodeToolSelectionForWire(['ts-1:jira.search', 'inst-a:mcp_notion_search'], groups))
      .toEqual(['jira.search', 'inst-a:mcp_notion_search']);
  });

  it('keeps an MCP key scoped while the catalog is reloading', () => {
    expect(encodeToolSelectionForWire(['inst-b:mcp_notion_search'], [])).toEqual(['inst-b:mcp_notion_search']);
  });

  it('keeps a disconnected instance scoped so another instance cannot claim it', () => {
    const groups = [{ fullNames: ['inst-a:mcp_notion_search'] }];
    expect(encodeToolSelectionForWire(['inst-b:mcp_notion_search'], groups)).toEqual(['inst-b:mcp_notion_search']);
  });
});

describe('resolveProjectToolKeys', () => {
  const groups = [
    { instanceId: 'inst-b', fullNames: ['inst-b:mcp_notion_search'] },
    { instanceId: 'inst-a', fullNames: ['inst-a:mcp_notion_search'] },
  ];

  it('maps a legacy bare MCP grant to the first instance only', () => {
    const { keys, legacyMcpKeys } = resolveProjectToolKeys(['mcp_notion_search'], groups);
    expect([...keys]).toEqual(['inst-a:mcp_notion_search']);
    expect([...legacyMcpKeys]).toEqual(['inst-a:mcp_notion_search']);
  });

  it('drops a scoped grant for an instance that no longer exists', () => {
    const { keys } = resolveProjectToolKeys(['inst-c:mcp_notion_search'], groups);
    expect([...keys]).toEqual([]);
  });
});
