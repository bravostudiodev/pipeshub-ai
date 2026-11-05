import { create } from 'zustand';

const EMPTY_IDS: ReadonlySet<string> = new Set();

/** Selection is keyed by sidebar so a selection in the chat list never shows up in an agent's list. */
export function selectionScopeFor(agentId?: string): string {
  return agentId ?? 'chats';
}

interface SidebarSelectionState {
  scope: string | null;
  ids: ReadonlySet<string>;
  toggle: (scope: string, id: string) => void;
  setMany: (scope: string, ids: string[], selected: boolean) => void;
  remove: (ids: string[]) => void;
  clear: () => void;
}

export const useSidebarSelectionStore = create<SidebarSelectionState>((set) => ({
  scope: null,
  ids: EMPTY_IDS,
  toggle: (scope, id) =>
    set((state) => {
      const next = new Set(state.scope === scope ? state.ids : []);
      if (!next.delete(id)) next.add(id);
      return { scope: next.size > 0 ? scope : null, ids: next };
    }),
  setMany: (scope, ids, selected) =>
    set((state) => {
      const next = new Set(state.scope === scope ? state.ids : []);
      for (const id of ids) {
        if (selected) next.add(id);
        else next.delete(id);
      }
      return { scope: next.size > 0 ? scope : null, ids: next };
    }),
  remove: (ids) =>
    set((state) => {
      const next = new Set(state.ids);
      for (const id of ids) next.delete(id);
      return { scope: next.size > 0 ? state.scope : null, ids: next };
    }),
  clear: () => set({ scope: null, ids: EMPTY_IDS }),
}));

export function selectIdsForScope(scope: string) {
  return (state: SidebarSelectionState): ReadonlySet<string> =>
    state.scope === scope ? state.ids : EMPTY_IDS;
}
