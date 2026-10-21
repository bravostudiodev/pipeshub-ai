'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { Flex, Text } from '@radix-ui/themes';
import { PipesHubIcon } from './pipes-hub-icon';

// Lightweight fallback rendered when the Lottie chunk hasn't loaded yet
// or when it fails to load (e.g. navigation interrupts the download).
function LogoFallback(props: { style?: React.CSSProperties }) {
  return <PipesHubIcon size={48} style={props.style} />;
}

// @lottiefiles/dotlottie-react accesses `document` at module init — must be
// dynamically imported with ssr:false so it is never evaluated on the server
// during static export pre-rendering.
// The `.catch()` prevents a ChunkLoadError from crashing the app when a
// navigation (e.g. post-login redirect) cancels the chunk download mid-flight.
const DotLottieReact = dynamic(
  () =>
    import('@lottiefiles/dotlottie-react')
      .then((m) => m.DotLottieReact)
      .catch(() => LogoFallback as React.ComponentType<Record<string, unknown>>),
  {
    ssr: false,
    loading: () => <LogoFallback />,
  }
);

// Catches runtime render errors from the Lottie player (e.g. if a lottie file
// is corrupt or the player tears down during unmount).
class LottieErrorBoundary extends React.Component<
  { children: React.ReactNode; fallbackSize: number },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) {
      return <LogoFallback style={{ width: this.props.fallbackSize, height: this.props.fallbackSize }} />;
    }
    return this.props.children;
  }
}

export type LottieVariant = 'loader' | 'listening' | 'thinking' | 'still';

interface LottieLoaderProps {
  variant?: LottieVariant;
  size?: number;
  loop?: boolean;
  autoplay?: boolean;
  style?: React.CSSProperties;
  showLabel?: boolean;
  label?: string;
}

const LOTTIE_MAP: Record<LottieVariant, string> = {
  loader: '/lottie-files/Loader.lottie',
  listening: '/lottie-files/Listening.lottie',
  thinking: '/lottie-files/Thinking.lottie',
  still: '/lottie-files/Still.lottie',
};

export function LottieLoader({
  variant = 'loader',
  size = 32,
  loop = true,
  autoplay = true,
  style,
  showLabel = false,
  label = 'Loading...',
}: LottieLoaderProps) {
  const lottie = (
    <LottieErrorBoundary fallbackSize={size}>
      <DotLottieReact
        src={LOTTIE_MAP[variant]}
        loop={loop}
        autoplay={autoplay}
        style={{
          width: size,
          height: size,
          ...style,
        }}
      />
    </LottieErrorBoundary>
  );

  const visual = variant === 'loader' || variant === 'thinking' || variant === 'still' ? (
    <PipesHubIcon size={size} style={style} />
  ) : lottie;

  if (!showLabel) return visual;

  return (
    <Flex direction="column" align="center" gap="2">
      {visual}
      <Text size="2" weight="medium" style={{ color: 'var(--slate-11)' }}>
        {label}
      </Text>
    </Flex>
  );
}
