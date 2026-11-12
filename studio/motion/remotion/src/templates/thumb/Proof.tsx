import React from 'react';
import {Img, staticFile} from 'remotion';
import type {ChecklistItem, ScreenshotBox} from './types';

/** "Payment received" card (Kai Stone's "I TESTED THIS FOR 3 MONTHS + Payment received
 * $297.00"): a white rounded card, small grey label, big green bold amount. The amount
 * string is always the caller's -- never computed or guessed here. */
export const PaymentCard: React.FC<{amount: string}> = ({amount}) => (
  <div
    style={{
      position: 'absolute',
      left: 68,
      bottom: 112, // clears the brand logo bug at bottom:40 (studio/thumbnail.py's `logo` prop)
      background: '#FFFFFF',
      borderRadius: 14,
      padding: '14px 26px 16px',
      transform: 'rotate(-3deg)',
      boxShadow: '0 22px 44px rgba(0,0,0,0.45)',
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
    }}
  >
    <div style={{fontFamily: 'Inter', fontSize: 15, color: '#64748B', fontWeight: 600, letterSpacing: '0.2px'}}>
      Payment received
    </div>
    <div style={{fontFamily: 'Montserrat', fontWeight: 800, fontSize: 42, color: '#16A34A', lineHeight: 1}}>
      {amount}
    </div>
  </div>
);

/** 2-3 row checklist (Keaton Walker / GHL tutorial style): one row ticked and highlighted
 * in the brand accent colour, the rest plain -- "2-3 items with one ticked and
 * highlighted" from the reference rules. */
export const ChecklistCard: React.FC<{items: ChecklistItem[]; accent: string}> = ({items, accent}) => (
  // bottom:112 clears the brand logo bug at bottom:40 the same way PaymentCard does
  <div style={{position: 'absolute', left: 68, bottom: 112, display: 'flex', flexDirection: 'column', gap: 10}}>
    {items.slice(0, 3).map((it, i) => (
      <div
        key={i}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          background: it.done ? accent : 'rgba(255,255,255,0.10)',
          borderRadius: 10,
          padding: '9px 18px',
          boxShadow: it.done ? '0 12px 26px rgba(0,0,0,0.35)' : 'none',
        }}
      >
        <span
          style={{
            width: 26,
            height: 26,
            borderRadius: '50%',
            background: it.done ? 'rgba(0,0,0,0.18)' : 'rgba(255,255,255,0.18)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFFFFF',
            fontSize: 15,
            fontWeight: 900,
            flexShrink: 0,
          }}
        >
          {it.done ? '✓' : '✗'}
        </span>
        <span
          style={{
            fontFamily: 'Montserrat',
            fontWeight: 800,
            fontSize: 25,
            color: '#FFFFFF',
            textDecoration: it.done ? 'none' : 'line-through',
            opacity: it.done ? 1 : 0.7,
            whiteSpace: 'nowrap',
          }}
        >
          {it.text}
        </span>
      </div>
    ))}
  </div>
);

/** A hand-drawn-looking circle (slightly wobbly ellipse, not a perfect CAD oval) around a
 * region of the screenshot -- the "screenshot card" proof element. `box` is in fractions
 * (0-1) of the card's own width/height. */
function ellipsePath(box: ScreenshotBox, w: number, h: number): string {
  const cx = (box.x + box.w / 2) * w;
  const cy = (box.y + box.h / 2) * h;
  const rx = (box.w / 2) * w;
  const ry = (box.h / 2) * h;
  const n = 20;
  const pts: string[] = [];
  for (let i = 0; i <= n; i++) {
    const t = (i / n) * Math.PI * 2;
    const wobble = 1 + Math.sin(t * 3 + 0.7) * 0.035 + (i % 2 === 0 ? 0.018 : -0.012);
    const x = cx + Math.cos(t) * rx * wobble;
    const y = cy + Math.sin(t) * ry * wobble;
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return `M${pts.join(' L')} Z`;
}

const SCREEN_W = 500;
const SCREEN_H = 282;

// Kept on the SAME side as the title (left), well clear of the big edge-cropped face on
// the right -- studio/thumbnail.py reserves a matching top band for the title column
// (see fit_title's max_height for layout="screenshot") so the two never collide.
export const ScreenshotCard: React.FC<{src: string; box?: ScreenshotBox}> = ({src, box}) => (
  <div
    style={{
      position: 'absolute',
      left: 64,
      top: 48,
      width: SCREEN_W,
      height: SCREEN_H,
      borderRadius: 16,
      overflow: 'hidden',
      transform: 'rotate(-3deg)',
      border: '5px solid rgba(255,255,255,0.95)',
      boxShadow: '0 32px 60px rgba(0,0,0,0.55)',
    }}
  >
    <Img src={staticFile(src)} style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'left top'}} />
    {box ? (
      <svg viewBox={`0 0 ${SCREEN_W} ${SCREEN_H}`} style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}>
        <path d={ellipsePath(box, SCREEN_W, SCREEN_H)} fill="none" stroke="#FF3030" strokeWidth={7} strokeLinecap="round" />
      </svg>
    ) : null}
  </div>
);

/** A small rounded icon chip, e.g. a Google Maps pin drawn as plain SVG shapes (no
 * trademarked logo file) -- the "icon chips" proof element, used for local-SEO style
 * titles like "GET MORE CALLS". */
export const MapsPinChip: React.FC<{label?: string}> = ({label = 'Google Maps'}) => (
  <div
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 10,
      background: '#FFFFFF',
      borderRadius: 999,
      padding: '8px 20px 8px 10px',
      boxShadow: '0 14px 26px rgba(0,0,0,0.32)',
    }}
  >
    <svg width={28} height={28} viewBox="0 0 24 24">
      <path d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7z" fill="#EA4335" />
      <circle cx="12" cy="9" r="2.6" fill="#FFFFFF" />
    </svg>
    <span style={{fontFamily: 'Montserrat', fontWeight: 700, fontSize: 19, color: '#14110F'}}>{label}</span>
  </div>
);
