import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, depthShadow, Fill, titleFamily, unit, useFonts} from '../shared';

export type KineticTitleProps = BaseProps & {
  text: string;
  subtitle?: string;
  /** vertical anchor 0..1 (0.42 sits just above eye line for a talking head) */
  y?: number;
};

/**
 * Large title that rises toward the camera with depth: each word springs up out of a
 * soft blur, the whole line settles from a slight 3D tilt and overscale, a light sweep
 * crosses the letters, and it exits by pushing toward the viewer while fading.
 * With placement "behind" the same layer is composited behind the speaker.
 */
export const KineticTitle: React.FC<KineticTitleProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const words = (p.text || 'TITLE').split(/\s+/);
  const vertical = p.height > p.width;
  const maxW = p.width * (vertical ? 0.86 : 0.84);
  // Behind a vertical speaker the head fills the middle, so sit the title in the headroom.
  const anchorY = p.y ?? (vertical ? (p.placement === 'behind' ? 0.15 : 0.3) : 0.42);
  const longest = Math.max(...words.map((w) => w.length));
  const charsPerLine = vertical ? Math.max(8, longest) : Math.max(14, Math.ceil(p.text.length / 2));
  const fontSize = Math.min((maxW / (charsPerLine * 0.62)), (vertical ? 210 : 190) * u);

  const settle = spring({frame, fps, config: {damping: 18, stiffness: 90, mass: 0.9}});
  const exitStart = durationInFrames - Math.round(fps * 0.45);
  const exit = interpolate(frame, [exitStart, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.cubic),
  });
  const lineScale = interpolate(settle, [0, 1], [1.22, 1]) * (1 + exit * 0.18);
  const tilt = interpolate(settle, [0, 1], [28, 0]);
  const sweep = interpolate(frame, [fps * 0.35, fps * 1.35], [-40, 140], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.inOut(Easing.quad),
  });

  return (
    <Fill style={{perspective: 1400 * u}}>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: `${anchorY * 100}%`,
          transform: `translateY(-50%) scale(${lineScale}) rotateX(${tilt}deg)`,
          transformOrigin: '50% 60%',
          opacity: 1 - exit,
          filter: `blur(${exit * 10 * u}px)`,
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          columnGap: fontSize * 0.28,
          rowGap: fontSize * 0.02,
          padding: `0 ${p.width * 0.07}px`,
        }}
      >
        {words.map((w, i) => {
          const s = spring({frame: frame - i * 3, fps, config: {damping: 14, stiffness: 120, mass: 0.7}});
          return (
            <span
              key={i}
              style={{
                display: 'inline-block',
                fontFamily: titleFamily,
                fontWeight: 900,
                fontSize,
                lineHeight: 0.98,
                letterSpacing: `${interpolate(s, [0, 1], [0.08, -0.015])}em`,
                color: 'transparent',
                transform: `translateY(${interpolate(s, [0, 1], [0.55, 0]) * fontSize}px)`,
                opacity: interpolate(s, [0, 0.35], [0, 1], {extrapolateRight: 'clamp'}),
                // drop-shadow (not text-shadow) so the shadow sits behind the gradient-filled glyphs
                filter: `blur(${interpolate(s, [0, 1], [14 * u, 0])}px) drop-shadow(0 ${3 * u}px ${3 * u}px rgba(0,0,0,0.35)) drop-shadow(0 ${14 * u}px ${22 * u}px rgba(0,0,0,0.38)) drop-shadow(0 ${34 * u}px ${60 * u}px rgba(0,0,0,0.32))`,
                backgroundImage: `linear-gradient(100deg, ${p.colors.text} ${sweep - 18}%, #FFFFFF ${sweep}%, ${p.colors.text} ${sweep + 18}%)`,
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
              }}
            >
              {w}
            </span>
          );
        })}
      </div>
      {p.subtitle ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: `calc(${anchorY * 100}% + ${fontSize * 0.9}px)`,
            textAlign: 'center',
            fontFamily: titleFamily,
            fontWeight: 600,
            fontSize: fontSize * 0.26,
            letterSpacing: '0.32em',
            color: p.colors.primary,
            textShadow: depthShadow(u, 0.8),
            opacity: interpolate(frame, [fps * 0.5, fps * 0.9], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) * (1 - exit),
          }}
        >
          {p.subtitle.toUpperCase()}
        </div>
      ) : null}
    </Fill>
  );
};
