import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, depthShadow, Fill, titleFamily, unit, useFonts, withAlpha} from '../shared';

export type ChapterCardProps = BaseProps & {number: number; title: string};

/** Chapter marker: oversized outlined number, a line that draws across, and a
 * masked title reveal over a soft vignette on the left third of the frame. */
export const ChapterCard: React.FC<ChapterCardProps> = (p) => {
  useFonts();
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const out = interpolate(frame, [durationInFrames - fps * 0.4, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const numS = spring({frame, fps, config: {damping: 16, stiffness: 100}});
  const line = interpolate(frame, [4, fps * 0.6], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.exp)});
  const reveal = interpolate(frame, [8, fps * 0.75], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const numSize = (vertical ? 200 : 220) * u;
  const titleSize = (vertical ? 66 : 64) * u;
  const x = p.width * (vertical ? 0.08 : 0.07);
  const y = p.height * (vertical ? 0.2 : 0.5);
  return (
    <Fill style={{opacity: 1 - out}}>
      <Fill style={{background: `linear-gradient(90deg, ${withAlpha(p.colors.background, 0.62 * reveal)} 0%, ${withAlpha(p.colors.background, 0.25 * reveal)} 38%, rgba(0,0,0,0) 62%)`}}>{null}</Fill>
      <div style={{position: 'absolute', left: x, top: y, transform: 'translateY(-50%)'}}>
        <div style={{fontFamily: titleFamily, fontWeight: 900, fontSize: numSize, lineHeight: 0.85,
          color: 'transparent', WebkitTextStroke: `${3 * u}px ${p.colors.primary}`,
          transform: `translateX(${interpolate(numS, [0, 1], [-40 * u, 0])}px) scale(${interpolate(numS, [0, 1], [1.15, 1])})`,
          transformOrigin: 'left center', opacity: numS}}>
          {String(p.number).padStart(2, '0')}
        </div>
        <div style={{height: 4 * u, width: (vertical ? 520 : 640) * u * line, background: p.colors.primary,
          margin: `${18 * u}px 0 ${20 * u}px`, borderRadius: 2 * u,
          boxShadow: `0 0 ${18 * u}px ${withAlpha(p.colors.primary, 0.6)}`}} />
        <div style={{overflow: 'hidden', maxWidth: p.width * (vertical ? 0.84 : 0.55)}}>
          <div style={{fontFamily: titleFamily, fontWeight: 800, fontSize: titleSize, lineHeight: 1.08,
            color: p.colors.text, textShadow: depthShadow(u, 0.9), letterSpacing: '-0.01em',
            transform: `translateY(${(1 - reveal) * 105}%)`}}>
            {p.title}
          </div>
        </div>
      </div>
    </Fill>
  );
};
