'use client';

import React from 'react';

interface PipesHubIconProps {
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

/** Shared company mark. `color` remains accepted for call-site compatibility. */
export function PipesHubIcon({
  size = 80,
  style,
  className,
}: PipesHubIconProps) {
  return (
    <img
      src="/ob.svg"
      alt=""
      width={size}
      height={size}
      style={{ display: 'inline-flex', flexShrink: 0, objectFit: 'contain', ...style }}
      className={className}
    />
  );
}
