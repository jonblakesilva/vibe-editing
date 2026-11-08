import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, depthShadow, Fill, titleFamily, unit, useFonts, withAlpha} from '../shared';

export type LowerThirdProps = BaseProps & {name: string; title?: string};

/** Frosted card with a brand accent bar that wipes in, name and role staggered. */
export const LowerThird: React.FC<LowerThirdProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const inS = spring({frame, fps, config: {damping: 20, stiffness: 110}});
  const out = interpolate(frame, [durationInFrames - fps * 0.4, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const bar = interpolate(frame, [0, fps * 0.35], [0, 1], {extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const nameS = spring({frame: frame - 5, fps, config: {damping: 18, stiffness: 120}});
  const roleS = spring({frame: frame - 10, fps, config: {damping: 18, stiffness: 120}});
  const left = p.width * (vertical ? 0.07 : 0.06);
  // stays above the caption band (captions occupy ~8-14% from the bottom in 16:9, ~27-33% in 9:16)
  const bottom = p.height * (vertical ? 0.355 : 0.062);  // 16:9: same band as captions (captions slide right while it shows)
  const nameSize = (vertical ? 58 : 54) * u;
  return (
    <Fill>
      <div
        style={{
          position: 'absolute', left, bottom,
          transform: `translateX(${interpolate(inS, [0, 1], [-60 * u, 0]) - out * 40 * u}px)`,
          opacity: interpolate(inS, [0, 0.4], [0, 1], {extrapolateRight: 'clamp'}) * (1 - out),
          display: 'flex', alignItems: 'stretch',
          filter: `drop-shadow(0 ${16 * u}px ${30 * u}px rgba(0,0,0,0.35))`,
        }}
      >
        <div style={{width: 10 * u, background: p.colors.primary, borderRadius: 4 * u,
          transform: `scaleY(${bar})`, transformOrigin: 'bottom'}} />
        <div
          style={{
            marginLeft: 14 * u, padding: `${18 * u}px ${30 * u}px ${18 * u}px ${24 * u}px`,
            background: `linear-gradient(135deg, ${withAlpha(p.colors.background, 0.78)}, ${withAlpha(p.colors.background, 0.55)})`,
            borderRadius: 14 * u, border: `${1.5 * u}px solid rgba(255,255,255,0.12)`,
            clipPath: `inset(0 ${(1 - bar) * 100}% 0 0 round ${14 * u}px)`,
          }}
        >
          <div style={{fontFamily: titleFamily, fontWeight: 800, fontSize: nameSize, color: p.colors.text,
            letterSpacing: '-0.01em', lineHeight: 1.05, textShadow: depthShadow(u, 0.4),
            transform: `translateY(${interpolate(nameS, [0, 1], [18 * u, 0])}px)`, opacity: nameS}}>
            {p.name}
          </div>
          {p.title ? (
            <div style={{fontFamily: titleFamily, fontWeight: 600, fontSize: nameSize * 0.48, marginTop: 6 * u,
              color: p.colors.highlight || p.colors.primary, letterSpacing: '0.14em', textTransform: 'uppercase',
              transform: `translateY(${interpolate(roleS, [0, 1], [14 * u, 0])}px)`, opacity: roleS}}>
              {p.title}
            </div>
          ) : null}
        </div>
      </div>
    </Fill>
  );
};
