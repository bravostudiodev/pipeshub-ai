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
    <span
      className={`oddjeeves-logo ${className ?? ''}`}
      style={{ width: size, height: size, display: 'inline-flex', flexShrink: 0, ...style }}
      aria-hidden="true"
    >
      <img src="/ob.svg" alt="" width={size} height={size} className="oddjeeves-logo-dark" />
      <img src="/ob-light.svg" alt="" width={size} height={size} className="oddjeeves-logo-light" />
    </span>
  );
}
