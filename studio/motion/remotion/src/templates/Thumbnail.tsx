import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {BaseProps, titleFamily, useFonts, withAlpha} from '../shared';

export type ThumbnailProps = BaseProps & {
  title: string;
  highlight?: string;   // word(s) drawn in the brand highlight color
  image?: string;       // speaker cut-out (transparent PNG), staged into public/
  background?: string;  // the original frame, used blurred behind everything
  logo?: string;
};

/** 1280x720 YouTube thumbnail: blurred frame + brand gradient, the speaker cut out on the
 * right with a soft glow, and a 2-4 line title on the left in the brand title font. */
export const Thumbnail: React.FC<ThumbnailProps> = (p) => {
  useFonts(p.fontTitle);
  const words = p.title.toUpperCase().split(/\s+/).filter(Boolean);
  const hi = new Set((p.highlight || '').toUpperCase().split(/\s+/).filter(Boolean));
  // fewer words -> bigger type; long titles still fit in four lines
  const size = words.length <= 3 ? 150 : words.length <= 5 ? 122 : words.length <= 7 ? 104 : 88;
  const navy = p.colors.background;
  return (
    <AbsoluteFill style={{background: navy, overflow: 'hidden'}}>
      {p.background ? (
        <Img src={staticFile(p.background)} style={{position: 'absolute', inset: -40, width: 'calc(100% + 80px)',
          height: 'calc(100% + 80px)', objectFit: 'cover', filter: 'blur(18px) saturate(0.8) brightness(0.55)'}} />
      ) : null}
      <AbsoluteFill style={{background: `linear-gradient(90deg, ${withAlpha(navy, 0.97)} 0%, ${withAlpha(navy, 0.9)} 42%, ${withAlpha(navy, 0.25)} 75%, ${withAlpha(navy, 0.1)} 100%)`}} />
      <div style={{position: 'absolute', right: -30, bottom: -120, width: 760, height: 760, borderRadius: '50%',
        background: `radial-gradient(circle, ${withAlpha(p.colors.primary, 0.55)} 0%, ${withAlpha(p.colors.primary, 0)} 65%)`}} />
      {p.image ? (
        <Img src={staticFile(p.image)} style={{position: 'absolute', right: -10, bottom: 0, height: 700, width: 660,
          objectFit: 'contain', objectPosition: 'right bottom',
          filter: `drop-shadow(0 0 3px #fff) drop-shadow(0 18px 40px rgba(0,0,0,0.55))`}} />
      ) : null}
      <div style={{position: 'absolute', left: 64, top: 0, bottom: 0, width: 640, display: 'flex',
        flexDirection: 'column', justifyContent: 'center'}}>
        <div style={{width: 120, height: 14, borderRadius: 7, background: p.colors.highlight, marginBottom: 26}} />
        <div style={{fontFamily: titleFamily, fontWeight: 900, fontSize: size, lineHeight: 0.98, color: '#fff',
          letterSpacing: '-0.02em', textShadow: '0 6px 0 rgba(0,0,0,0.35), 0 12px 30px rgba(0,0,0,0.5)'}}>
          {words.map((w, i) => (
            <span key={i} style={{color: hi.has(w.replace(/[^\w$%,.]/g, '')) || hi.has(w) ? p.colors.highlight : '#fff'}}>
              {w}{i < words.length - 1 ? ' ' : ''}
            </span>
          ))}
        </div>
      </div>
      {p.logo ? (
        <Img src={staticFile(p.logo)} style={{position: 'absolute', left: 64, bottom: 40, height: 56, width: 'auto',
          opacity: 0.95}} />
      ) : null}
    </AbsoluteFill>
  );
};
