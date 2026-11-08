import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, titleFamily, unit, useFonts, withAlpha} from '../shared';

export type CallToActionProps = BaseProps & {text: string; url?: string};

/** Pill button that springs in, a glow that breathes, and an arrow that nudges. */
export const CallToAction: React.FC<CallToActionProps> = (p) => {
  useFonts();
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const s = spring({frame, fps, config: {damping: 11, stiffness: 140, mass: 0.8}});
  const out = interpolate(frame, [durationInFrames - fps * 0.35, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const pulse = 0.5 + 0.5 * Math.sin((frame / fps) * Math.PI * 2 * 0.9);
  const nudge = Math.max(0, Math.sin((frame / fps) * Math.PI * 2 * 1.2)) * 10 * u;
  const size = (vertical ? 52 : 46) * u;
  return (
    <Fill style={{display: 'flex', justifyContent: 'center', alignItems: 'flex-end',
      paddingBottom: p.height * (vertical ? 0.4 : 0.14)}}>
      <div style={{transform: `scale(${interpolate(s, [0, 1], [0.6, 1]) * (1 - out * 0.1)}) translateY(${(1 - s) * 40 * u}px)`,
        opacity: Math.min(1, s * 1.4) * (1 - out), display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 * u}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 18 * u,
          padding: `${22 * u}px ${44 * u}px`, borderRadius: 999,
          background: `linear-gradient(180deg, ${p.colors.primary}, ${withAlpha(p.colors.primary, 0.86)})`,
          boxShadow: `0 ${14 * u}px ${36 * u}px rgba(0,0,0,0.35), 0 0 ${(30 + pulse * 30) * u}px ${withAlpha(p.colors.primary, 0.35 + pulse * 0.25)}`,
          border: `${2 * u}px solid rgba(255,255,255,0.35)`}}>
          <span style={{fontFamily: titleFamily, fontWeight: 900, fontSize: size, color: p.colors.background,
            letterSpacing: '0.01em', textTransform: 'uppercase', whiteSpace: 'nowrap'}}>{p.text}</span>
          <svg width={size * 0.9} height={size * 0.9} viewBox="0 0 24 24" style={{transform: `translateX(${nudge}px)`}}>
            <path d="M5 12h12M13 6l6 6-6 6" stroke={p.colors.background} strokeWidth={3} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        {p.url ? (
          <div style={{fontFamily: titleFamily, fontWeight: 700, fontSize: size * 0.55, color: p.colors.text,
            letterSpacing: '0.06em', textShadow: '0 2px 10px rgba(0,0,0,0.6)',
            opacity: interpolate(frame, [fps * 0.3, fps * 0.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            {p.url}
          </div>
        ) : null}
      </div>
    </Fill>
  );
};
