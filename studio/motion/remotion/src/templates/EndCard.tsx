import React from 'react';
import {Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, readableOn, titleFamily, unit, useFonts, withAlpha} from '../shared';

export type EndCardProps = BaseProps & {text: string; url?: string; tagline?: string; logo?: string | null};

/**
 * Branded outro: the picture darkens into the brand navy from below, the logo settles in,
 * then the call-to-action button and URL. Overlay, so the speaker's last line still plays.
 */
export const EndCard: React.FC<EndCardProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const navy = p.colors.background || '#0F1E4A';
  const veil = interpolate(frame, [0, fps * 0.6], [0, 1], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const logoS = spring({frame: frame - 6, fps, config: {damping: 16, stiffness: 90}});
  const btnS = spring({frame: frame - 16, fps, config: {damping: 12, stiffness: 130}});
  const out = interpolate(frame, [durationInFrames - 6, durationInFrames], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const btn = p.colors.highlight || p.colors.primary;
  return (
    <Fill style={{opacity: 1 - out}}>
      <Fill style={{background: `linear-gradient(0deg, ${withAlpha(navy, 0.96 * veil)} 0%, ${withAlpha(navy, 0.82 * veil)} ${vertical ? 55 : 48}%, ${withAlpha(navy, 0)} ${vertical ? 80 : 75}%)`}}>{null}</Fill>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: p.height * (vertical ? 0.38 : 0.2), display: 'flex',  // above the caption band
        flexDirection: 'column', alignItems: 'center', gap: 22 * u}}>
        {p.logo ? (
          <Img src={staticFile(p.logo)} style={{height: (vertical ? 210 : 190) * u, opacity: logoS,
            transform: `translateY(${(1 - logoS) * 30 * u}px) scale(${0.9 + 0.1 * logoS})`}} />
        ) : null}
        {p.tagline ? (
          <div style={{fontFamily: titleFamily, fontWeight: 600, fontSize: 28 * u, color: withAlpha('#FFFFFF', 0.85),
            letterSpacing: '0.04em', opacity: logoS}}>{p.tagline}</div>
        ) : null}
        <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 * u, opacity: btnS,
          transform: `scale(${0.8 + 0.2 * btnS})`}}>
          <div style={{padding: `${20 * u}px ${46 * u}px`, borderRadius: 999, background: btn, color: readableOn(btn),
            fontFamily: titleFamily, fontWeight: 900, fontSize: 40 * u, textTransform: 'uppercase',
            boxShadow: `0 ${12 * u}px ${30 * u}px rgba(0,0,0,0.35), 0 0 ${40 * u}px ${withAlpha(btn, 0.45)}`}}>{p.text}</div>
          {p.url ? <div style={{fontFamily: titleFamily, fontWeight: 700, fontSize: 26 * u, color: '#FFFFFF'}}>{p.url}</div> : null}
        </div>
      </div>
    </Fill>
  );
};
