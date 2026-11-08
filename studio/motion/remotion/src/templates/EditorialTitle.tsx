import React from 'react';
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, serifFamily, unit, useFonts} from '../shared';

export type EditorialTitleProps = BaseProps & {text: string; y?: number; faceX?: number; faceW?: number};

/**
 * Magazine-style headline: huge serif capitals stacked tight, each line revealed upward
 * from behind a mask with a slow ease, a faint glow for depth, gentle drift while it holds.
 * Designed to sit behind the speaker (placement "behind").
 */
export const EditorialTitle: React.FC<EditorialTitleProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const words = (p.text || 'TITLE').toUpperCase().split(/\s+/);
  // break into balanced lines of ~1-2 words (vertical) or ~2-3 words (landscape)
  const perLine = vertical ? Math.max(1, Math.ceil(words.length / 3)) : Math.max(1, Math.ceil(words.length / 3));
  const lines: string[] = [];
  for (let i = 0; i < words.length; i += perLine) lines.push(words.slice(i, i + perLine).join(' '));
  const longest = Math.max(...lines.map((l) => l.length));
  // landscape with a known speaker position: use the open side of the frame
  // the head is ~1.75x the detected face box; put the title in the wider open side
  const headHalf = ((p.faceW ?? 0.2) * 1.75) / 2;
  const freeL = p.faceX != null ? p.faceX - headHalf : 0;
  const freeR = p.faceX != null ? 1 - (p.faceX + headHalf) : 0;
  const side = !vertical && p.faceX != null && Math.max(freeL, freeR) > 0.18 ? (freeR >= freeL ? 'right' : 'left') : null;
  const colW = side ? p.width * (Math.max(freeL, freeR) - 0.05) : p.width * 0.86;
  const size = Math.min(colW / (longest * 0.6), (vertical ? 230 : 210) * u);
  const out = interpolate(frame, [durationInFrames - fps * 0.5, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const drift = interpolate(frame, [0, durationInFrames], [0, -12 * u]);
  return (
    <Fill>
      <div style={{position: 'absolute', left: side === 'right' ? p.width * (1 - freeR + 0.02) : side === 'left' ? p.width * 0.03 : 0,
        width: side ? colW : undefined, right: side ? undefined : 0,
        top: `${(p.y ?? (vertical ? 0.16 : side ? 0.18 : 0.2)) * 100}%`,
        transform: `translateY(${drift}px)`, textAlign: side === 'right' ? 'left' : side === 'left' ? 'right' : 'center', opacity: 1 - out}}>
        {lines.map((line, i) => {
          const t = interpolate(frame, [i * 5, i * 5 + fps * 0.7], [0, 1], {
            extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.16, 1, 0.3, 1)});
          return (
            <div key={i} style={{overflow: 'hidden', lineHeight: 0.92, paddingTop: size * 0.04}}>
              <div style={{fontFamily: serifFamily, fontSize: size, color: p.colors.text, letterSpacing: '-0.01em',
                transform: `translateY(${(1 - t) * 100}%)`,
                textShadow: `0 ${6 * u}px ${30 * u}px rgba(0,0,0,0.25), 0 0 ${60 * u}px rgba(255,255,255,0.08)`}}>
                {line}
              </div>
            </div>
          );
        })}
      </div>
    </Fill>
  );
};
