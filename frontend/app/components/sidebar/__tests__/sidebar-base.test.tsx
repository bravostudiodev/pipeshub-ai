import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { Theme } from '@radix-ui/themes';
import { SidebarBase } from '../sidebar-base';

vi.mock('react-i18next', async () => {
  const { useState } = await import('react');
  return {
    // Must call a real hook: React only detects a shrunken hook list once at least one
    // hook has run, and the real useTranslation always does.
    useTranslation: () => { const [t] = useState(() => (key: string) => key); return { t }; },
  };
});

afterEach(cleanup);

// React 19 reports render errors through window.reportError, not by throwing from
// render(); a boundary is the only way the test can see a hook-order failure.
class Catcher extends React.Component<{ onError: (e: Error) => void; children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { this.props.onError(error); }
  render() { return this.state.failed ? null : this.props.children; }
}

describe('SidebarBase', () => {
  it('survives the first-paint desktop → mobile switch that useIsMobile produces', () => {
    // useIsMobile is false on the first render and true after mount, so the same
    // element must be able to re-render across the breakpoint without a hook-order error.
    const errors: Error[] = [];
    const wrap = (ui: React.ReactNode) => <Theme><Catcher onError={(e) => errors.push(e)}>{ui}</Catcher></Theme>;
    const { rerender } = render(wrap(<SidebarBase isMobile={false}><span>content</span></SidebarBase>));
    expect(screen.getByText('content')).toBeTruthy();

    rerender(wrap(<SidebarBase isMobile mobileOpen={false}><span>content</span></SidebarBase>));
    expect(errors).toEqual([]);
    expect(screen.queryByText('content')).toBeNull();

    rerender(wrap(
      <SidebarBase isMobile mobileOpen onMobileClose={() => {}} header={<span>hdr</span>}><span>content</span></SidebarBase>,
    ));
    expect(errors).toEqual([]);
    expect(screen.getByText('content')).toBeTruthy();
    expect(screen.getByLabelText('sidebar.close')).toBeTruthy();

    rerender(wrap(<SidebarBase isMobile={false}><span>content</span></SidebarBase>));
    expect(errors).toEqual([]);
    expect(screen.getByText('content')).toBeTruthy();
  });
});
