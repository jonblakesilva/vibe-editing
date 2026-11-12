import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import type {BaseProps} from '../../shared';
import {withAlpha} from '../../shared';
import {headlineFamily, useHeadlineFont} from './fonts';

/** 1080x1920 Shorts cover: the top half is a screen/background frame, the bottom half is
 * the face, and a rounded navy pill straddles the seam holding the (already wrapped and
 * sized) title with one highlighted word in yellow and a thin light-blue border --
 * matching the reference Shorts-cover rule exactly. */
export const ShortsCover: React.FC<
  BaseProps & {image?: string; background?: string; lines: string[]; size: number; highlight: string; logo?: string}
> = (p) => {
  useHeadlineFont();
  const hi = new Set((p.highlight || '').toUpperCase().split(/\s+/).filter(Boolean));
  const half = p.height / 2;
  return (
    <AbsoluteFill style={{background: p.colors.background, overflow: 'hidden'}}>
      <div style={{position: 'absolute', top: 0, left: 0, width: '100%', height: half, overflow: 'hidden'}}>
        {p.background ? (
          <Img src={staticFile(p.background)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        ) : (
          <div
            style={{
              width: '100%',
              height: '100%',
              background: `radial-gradient(circle at 50% 28%, ${withAlpha(p.colors.primary, 0.6)} 0%, ${p.colors.background} 72%)`,
            }}
          />
        )}
        <div style={{position: 'absolute', inset: 0, background: 'rgba(5,12,30,0.32)'}} />
      </div>
      {p.image ? (
        <Img
          src={staticFile(p.image)}
          style={{
            position: 'absolute',
            bottom: 0,
            left: '50%',
            transform: 'translateX(-50%)',
            height: half * 1.1,
            width: 'auto',
            maxWidth: '98%',
            objectFit: 'contain',
            objectPosition: 'bottom center',
            filter: 'drop-shadow(0 -12px 30px rgba(0,0,0,0.45))',
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          top: half - 96,
          left: '50%',
          transform: 'translateX(-50%)',
          width: p.width - 96,
          background: p.colors.background,
          borderRadius: 30,
          border: `3px solid ${withAlpha('#7DD3FC', 0.9)}`,
          boxShadow: '0 22px 52px rgba(0,0,0,0.5)',
          padding: '22px 32px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 4,
        }}
      >
        {p.lines.map((line, li) => {
          const words = line.split(/\s+/).filter(Boolean);
          return (
            <div
              key={li}
              style={{
                fontFamily: headlineFamily,
                fontWeight: 400,
                fontSize: p.size,
                lineHeight: 1.1,
                color: '#FFFFFF',
                textAlign: 'center',
              }}
            >
              {words.map((w, i) => (
                <span key={i} style={{color: hi.has(w.replace(/[^\w$%.,+]/g, '')) ? '#FACC15' : '#FFFFFF'}}>
                  {w}
                  {i < words.length - 1 ? ' ' : ''}
                </span>
              ))}
            </div>
          );
        })}
      </div>
      {p.logo ? (
        <Img
          src={staticFile(p.logo)}
          style={{position: 'absolute', left: 40, top: 40, height: 46, width: 'auto', opacity: 0.95}}
        />
      ) : null}
    </AbsoluteFill>
  );
};
