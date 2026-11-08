import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, titleFamily, unit, useFonts} from '../shared';

export type CalloutProps = BaseProps & {
  text: string;
  /** position 0..1 of the callout's center */
  x?: number;
  y?: number;
  /** optional emoji/icon-free label above, e.g. "KEY POINT" */
  label?: string;
};

/** Key-point callout: a marker highlight sweeps behind the words, label on top. */
export const Callout: React.FC<CalloutProps> = (p) => {
  useFonts();
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const s = spring({frame, fps, config: {damping: 15, stiffness: 130}});
  const sweep = interpolate(frame, [fps * 0.15, fps * 0.55], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
  const out = interpolate(frame, [durationInFrames - fps * 0.3, durationInFrames], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const size = (vertical ? 64 : 56) * u;
  return (
    <Fill>
      <div style={{position: 'absolute', left: `${(p.x ?? (vertical ? 0.5 : 0.72)) * 100}%`, top: `${(p.y ?? (vertical ? 0.22 : 0.3)) * 100}%`,
        transform: `translate(-50%, -50%) scale(${interpolate(s, [0, 1], [0.85, 1])}) rotate(${interpolate(s, [0, 1], [-4, -1.5])}deg)`,
        opacity: s * (1 - out), textAlign: 'center', maxWidth: p.width * (vertical ? 0.84 : 0.42),
        filter: `drop-shadow(0 ${10 * u}px ${24 * u}px rgba(0,0,0,0.4))`}}>
        {p.label ? (
          <div style={{fontFamily: titleFamily, fontWeight: 800, fontSize: size * 0.36, letterSpacing: '0.3em',
            color: p.colors.text, marginBottom: 10 * u, opacity: sweep}}>{p.label.toUpperCase()}</div>
        ) : null}
        <span style={{position: 'relative', display: 'inline', fontFamily: titleFamily, fontWeight: 900,
          fontSize: size, lineHeight: 1.25, color: p.colors.background, padding: `0 ${12 * u}px`,
          boxDecorationBreak: 'clone', WebkitBoxDecorationBreak: 'clone',
          backgroundImage: `linear-gradient(${p.colors.highlight}, ${p.colors.highlight})`,
          backgroundRepeat: 'no-repeat', backgroundSize: `${sweep * 100}% 100%`}}>
          {p.text}
        </span>
      </div>
    </Fill>
  );
};
