import React from 'react';
import {Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {BaseProps, Fill, readableOn, titleFamily, unit, useFonts, withAlpha} from '../shared';

type Card = {title?: string; subtitle?: string; image?: string};
export type FloatingCardsProps = BaseProps & {cards: Card[]; y?: number; layout?: 'arc' | 'sides'};

/**
 * A fan of cards that springs up in an arc above the speaker's head and floats gently,
 * like a deck of examples. Cards are images (screenshots, thumbnails you own) or branded
 * text cards. Best placed "behind" so the speaker stays in front.
 */
export const FloatingCards: React.FC<FloatingCardsProps> = (p) => {
  useFonts(p.fontTitle);
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const u = unit(p);
  const vertical = p.height > p.width;
  const cards = (p.cards && p.cards.length ? p.cards : [{title: 'Card'}]).slice(0, p.layout === 'sides' ? 4 : 7);
  const n = cards.length;
  const sidesMode = p.layout === 'sides' && !vertical;
  const cw = (vertical ? 250 : sidesMode ? 205 : 230) * u, ch = cw * (sidesMode ? 1.18 : 1.42);
  const spread = vertical ? p.width * 0.8 : Math.min(p.width * 0.62, n * cw * 0.78);
  const out = interpolate(frame, [durationInFrames - fps * 0.4, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.in(Easing.cubic)});
  const baseY = p.height * (p.y ?? (vertical ? 0.2 : 0.3));
  return (
    <Fill style={{opacity: 1 - out}}>
      {cards.map((c, i) => {
        const k = n === 1 ? 0 : i / (n - 1) - 0.5; // -0.5 .. 0.5
        const s = spring({frame: frame - i * 3, fps, config: {damping: 14, stiffness: 110, mass: 0.8}});
        // 'sides': cards stack left and right of the speaker (for tight framing with no headroom)
        const sides = p.layout === 'sides' && !vertical;
        const leftSide = i % 2 === 0, row = Math.floor(i / 2);
        const x = sides ? (leftSide ? p.width * (0.04 + row * 0.03) : p.width * (0.96 - row * 0.03) - cw)
          : p.width / 2 + k * spread - cw / 2;
        const arc = sides ? p.height * 0.14 + row * (ch + 24 * u) - (baseY - ch / 2) : Math.abs(k) * Math.abs(k) * ch * 0.7;
        const float = Math.sin((frame / fps) * 1.6 + i) * 6 * u;
        const rot = sides ? (leftSide ? -4 : 4) * (row ? -1 : 1) : k * (vertical ? 22 : 26);
        const bg = i % 3 === 0 ? p.colors.primary : i % 3 === 1 ? (p.colors.background || '#0F1E4A') : p.colors.highlight;
        return (
          <div key={i} style={{position: 'absolute', left: x, top: baseY - ch / 2 + arc + float + (1 - s) * ch * 0.8,
            width: cw, height: ch, borderRadius: 18 * u, overflow: 'hidden', opacity: Math.min(1, s * 1.3),
            transform: `rotate(${rot * s}deg) scale(${0.7 + 0.3 * s})`, transformOrigin: '50% 120%',
            boxShadow: `0 ${18 * u}px ${40 * u}px rgba(0,0,0,0.35)`, border: `${2 * u}px solid rgba(255,255,255,0.18)`,
            background: c.image ? '#000' : `linear-gradient(160deg, ${bg}, ${withAlpha(bg, 0.78)})`}}>
            {c.image ? (
              <Img src={staticFile(c.image)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
            ) : (
              <div style={{position: 'absolute', inset: 0, padding: 20 * u, display: 'flex', flexDirection: 'column',
                justifyContent: 'flex-end', color: readableOn(bg), fontFamily: titleFamily}}>
                <div style={{fontWeight: 800, fontSize: 30 * u, lineHeight: 1.05}}>{c.title}</div>
                {c.subtitle ? <div style={{fontWeight: 600, fontSize: 17 * u, opacity: 0.8, marginTop: 6 * u}}>{c.subtitle}</div> : null}
              </div>
            )}
          </div>
        );
      })}
    </Fill>
  );
};
