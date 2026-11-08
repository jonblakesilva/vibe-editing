import React from 'react';
import {Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, titleFamily, unit, useFonts, withAlpha} from '../shared';

type Stat = {value: string; label: string};
export type StatPanelsProps = BaseProps & {stats: Stat[]};

const countUp = (value: string, t: number) => {
  // "25,000" counts up from 0; "100+" keeps its suffix; non-numbers just appear
  const m = value.match(/^([^\d]*)([\d,.]+)(.*)$/);
  if (!m) return value;
  const target = parseFloat(m[2].replace(/,/g, ''));
  const cur = Math.round(target * t);
  return `${m[1]}${cur.toLocaleString('en-US')}${m[3]}`;
};

/**
 * Frosted-glass panels that slide in beside the speaker (left and right), each with a
 * big counting number, a label and a small animated bar chart.
 */
export const StatPanels: React.FC<StatPanelsProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const stats = (p.stats || []).slice(0, 2);
  const out = interpolate(frame, [durationInFrames - fps * 0.4, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const w = (vertical ? 470 : 380) * u;
  return (
    <Fill style={{opacity: 1 - out}}>
      {stats.map((st, i) => {
        const s = spring({frame: frame - i * 6, fps, config: {damping: 18, stiffness: 100}});
        const t = interpolate(frame, [i * 6 + 4, i * 6 + fps * 1.1], [0, 1], {
          extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
        const left = i === 0;
        const style: React.CSSProperties = vertical
          ? {left: i === 0 ? p.width * 0.035 : p.width * 0.965 - w, top: p.height * 0.075}
          : {[left ? 'left' : 'right']: p.width * 0.045, top: p.height * 0.24};
        return (
          <div key={i} style={{position: 'absolute', ...style, width: w, padding: `${22 * u}px ${26 * u}px`,
            borderRadius: 20 * u, background: `linear-gradient(150deg, ${withAlpha(p.colors.background || '#0F1E4A', 0.72)}, ${withAlpha(p.colors.background || '#0F1E4A', 0.45)})`,
            border: `${1.5 * u}px solid rgba(255,255,255,0.16)`, boxShadow: `0 ${20 * u}px ${50 * u}px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.12)`,
            backdropFilter: 'blur(8px)', opacity: s,
            transform: `translateX(${(1 - s) * (vertical ? 0 : left ? -60 : 60) * u}px) translateY(${(1 - s) * (vertical ? -30 : 0) * u}px)`}}>
            <div style={{fontFamily: titleFamily, fontWeight: 800, fontSize: 74 * u, lineHeight: 1, color: p.colors.text, letterSpacing: '-0.02em'}}>
              {countUp(st.value, t)}
            </div>
            <div style={{fontFamily: titleFamily, fontWeight: 600, fontSize: 27 * u, color: withAlpha('#FFFFFF', 0.82), marginTop: 8 * u}}>
              {st.label}
            </div>
            <div style={{display: 'flex', alignItems: 'flex-end', gap: 5 * u, height: 36 * u, marginTop: 14 * u}}>
              {Array.from({length: 14}).map((_, b) => (
                <div key={b} style={{flex: 1, borderRadius: 3 * u,
                  height: `${(0.25 + 0.75 * ((b + 1) / 14) * (0.7 + 0.3 * Math.sin(b * 1.7 + i))) * 100 * Math.min(1, t * 1.4 - b * 0.03)}%`,
                  background: b > 10 ? p.colors.highlight : withAlpha(p.colors.primary, 0.85)}} />
              ))}
            </div>
          </div>
        );
      })}
    </Fill>
  );
};
