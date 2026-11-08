import React from 'react';
import {Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, depthShadow, Fill, titleFamily, unit, useFonts, withAlpha} from '../shared';

export type BrandIntroProps = BaseProps & {brand: string; tagline?: string; logo?: string | null};

/** Short branded opener: animated gradient field, light streak, logo/name reveal.
 * Renders an opaque frame (it is a full-screen card, not an overlay). */
export const BrandIntro: React.FC<BrandIntroProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const t = frame / fps;
  const s = spring({frame: frame - 6, fps, config: {damping: 16, stiffness: 90}});
  const streak = interpolate(frame, [0, fps * 0.9], [-30, 130], {extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)});
  const out = interpolate(frame, [durationInFrames - fps * 0.35, durationInFrames], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <Fill style={{background: p.colors.background, opacity: 1 - out}}>
      <Fill style={{background: `radial-gradient(60% 60% at ${50 + 12 * Math.sin(t * 0.8)}% ${45 + 8 * Math.cos(t * 0.6)}%, ${withAlpha(p.colors.primary, 0.35)}, rgba(0,0,0,0) 70%)`}}>{null}</Fill>
      <Fill style={{background: `linear-gradient(105deg, rgba(255,255,255,0) ${streak - 8}%, rgba(255,255,255,0.18) ${streak}%, rgba(255,255,255,0) ${streak + 8}%)`}}>{null}</Fill>
      <Fill style={{display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 24 * u}}>
        {p.logo ? (
          <Img src={staticFile(p.logo)} style={{height: 380 * u, transform: `scale(${interpolate(s, [0, 1], [0.8, 1])})`, opacity: s}} />
        ) : null}
        {p.logo ? null : <div style={{fontFamily: titleFamily, fontWeight: 900, fontSize: 130 * u, color: p.colors.text,
          letterSpacing: `${interpolate(s, [0, 1], [0.3, 0.02])}em`, textShadow: depthShadow(u, 1),
          opacity: s, transform: `translateY(${(1 - s) * 30 * u}px)`}}>{p.brand.toUpperCase()}</div>}
        {p.tagline ? (
          <div style={{fontFamily: titleFamily, fontWeight: 600, fontSize: 40 * u, color: p.colors.primary, letterSpacing: '0.3em',
            opacity: interpolate(frame, [fps * 0.6, fps], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            {p.tagline.toUpperCase()}
          </div>
        ) : null}
      </Fill>
    </Fill>
  );
};
