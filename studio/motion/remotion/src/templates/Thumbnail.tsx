import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {BaseProps, useFonts, withAlpha} from '../shared';
import {HighlightTitle} from './thumb/Title';
import {Person} from './thumb/Person';
import {PaymentCard, ChecklistCard, ScreenshotCard, MapsPinChip} from './thumb/Proof';
import {ShortsCover} from './thumb/ShortsCover';
import {useHeadlineFont} from './thumb/fonts';
import type {ChecklistItem, ScreenshotBox, ThumbLayout} from './thumb/types';

export type ThumbnailProps = BaseProps & {
  layout?: ThumbLayout;
  title: string;
  highlight?: string;        // word(s) that sit on the solid highlight box
  titleSize?: number;        // px, pre-fit by studio/thumbnail.py's fit_title()
  titleLines?: string[];     // pre-wrapped lines; a naive fallback wraps `title` if absent
  image?: string;            // speaker cut-out (transparent PNG), staged into public/
  image2?: string;           // second speaker, "two-person" layout only
  background?: string;       // the original frame, blurred behind everything (video only)
  card?: string;             // legacy: a screen frame drawn as a tilted card (screencam projects)
  amount?: string;           // "payment" layout: the big green amount
  items?: ChecklistItem[];   // "checklist" layout: 2-3 rows, one ticked
  screenshot?: string;       // "screenshot" layout: the image/frame to feature
  screenshotBox?: ScreenshotBox; // optional hand-drawn circle over the screenshot
  chip?: 'maps_pin' | null;  // small icon chip next to the title
  logo?: string;
};

// naive fallbacks, used only if the Python side didn't pre-fit the title (e.g. a direct
// preview in Remotion Studio) -- studio/thumbnail.py's fit_title() is the real auto-fit.
function wrapFallback(title: string): string[] {
  const words = (title || '').toUpperCase().split(/\s+/).filter(Boolean);
  if (words.length <= 3) return [words.join(' ')];
  const mid = Math.ceil(words.length / 2);
  return [words.slice(0, mid).join(' '), words.slice(mid).join(' ')];
}
function sizeFallback(wordCount: number): number {
  return wordCount <= 3 ? 150 : wordCount <= 5 ? 122 : wordCount <= 7 ? 104 : 88;
}

/** YouTube thumbnail (1280x720) and Shorts cover (1080x1920, via layout="shorts-cover"),
 * built to match the reference creators the owner likes: a big edge-cropped face, a short
 * all-caps title with exactly one highlighted phrase, and an optional proof element
 * (payment card / checklist / screenshot / icon chip) chosen by `layout`. */
export const Thumbnail: React.FC<ThumbnailProps> = (p) => {
  useFonts(p.fontTitle);
  useHeadlineFont();
  const layout = p.layout || 'face-number';
  const words = (p.title || '').toUpperCase().split(/\s+/).filter(Boolean);
  const lines = p.titleLines && p.titleLines.length ? p.titleLines : wrapFallback(p.title);
  const size = p.titleSize ?? sizeFallback(words.length);

  if (layout === 'shorts-cover') {
    return (
      <ShortsCover
        {...p}
        lines={lines}
        size={size}
        highlight={p.highlight || ''}
      />
    );
  }

  const clean = layout === 'clean-white';
  const navy = p.colors.background;
  const align: 'left' | 'center' = layout === 'two-person' ? 'center' : 'left';
  // Reserves room for each layout's proof element so the title column never grows into
  // it -- matched on the Python side by the `max_height` passed to fit_title() for the
  // same layout (see studio/thumbnail.py, make()). Payment/checklist reserve space
  // below the title (the card sits at the bottom); screenshot reserves space above it
  // (the card sits top-left, title below).
  const BANDS: Partial<Record<ThumbLayout, {top: number; bottom: number}>> = {
    payment: {top: 0, bottom: 210},
    checklist: {top: 0, bottom: 290},
    screenshot: {top: 360, bottom: 100}, // also clears the brand logo bug at bottom:40
  };
  const band = BANDS[layout];
  const columnStyle: React.CSSProperties =
    align === 'center'
      ? {left: 0, right: 0, top: 0, bottom: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}
      : {left: 64, top: band?.top ?? 0, bottom: band?.bottom ?? 0, width: 640, display: 'flex', flexDirection: 'column', justifyContent: 'center'};

  return (
    <AbsoluteFill style={{background: clean ? '#FBF7F0' : navy, overflow: 'hidden'}}>
      {clean ? (
        <AbsoluteFill
          style={{background: 'radial-gradient(ellipse 120% 90% at 50% 0%, rgba(0,0,0,0.06) 0%, transparent 60%)'}}
        />
      ) : p.background ? (
        <>
          <Img
            src={staticFile(p.background)}
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
              filter: 'blur(26px) brightness(0.55) saturate(1.15)',
            }}
          />
          <AbsoluteFill
            style={{background: `linear-gradient(120deg, ${withAlpha(navy, 0.68)} 0%, ${withAlpha(navy, 0.32)} 55%, ${withAlpha(navy, 0.78)} 100%)`}}
          />
        </>
      ) : (
        <>
          {/* clean branded background: navy with a soft brand-blue glow and a faint grid */}
          <AbsoluteFill
            style={{background: `radial-gradient(ellipse 70% 90% at 78% 60%, ${withAlpha(p.colors.primary, 0.55)} 0%, ${withAlpha(p.colors.primary, 0.12)} 45%, ${withAlpha(navy, 0)} 70%), linear-gradient(120deg, ${navy} 0%, ${withAlpha(navy, 0.92)} 100%)`}}
          />
          <AbsoluteFill
            style={{backgroundImage: 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)', backgroundSize: '64px 64px'}}
          />
        </>
      )}
      {!clean ? (
        <div
          style={{
            position: 'absolute', right: 70, bottom: -140, width: 620, height: 620, borderRadius: '50%',
            background: `radial-gradient(circle, ${withAlpha(p.colors.highlight, 0.35)} 0%, ${withAlpha(p.colors.highlight, 0)} 62%)`,
          }}
        />
      ) : null}

      {layout === 'screenshot' && p.screenshot ? (
        <ScreenshotCard src={p.screenshot} box={p.screenshotBox} />
      ) : p.card ? (
        <div
          style={{
            position: 'absolute', right: 250, top: 70, width: 560, height: 315, borderRadius: 18, overflow: 'hidden',
            transform: 'rotate(-6deg)', border: '4px solid rgba(255,255,255,0.9)', boxShadow: '0 30px 60px rgba(0,0,0,0.55)',
          }}
        >
          <Img src={staticFile(p.card)} style={{width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'left top'}} />
        </div>
      ) : null}

      {layout === 'two-person' ? (
        <>
          {p.image ? <Person src={p.image} side="left" mirror /> : null}
          {p.image2 ? <Person src={p.image2} side="right" /> : null}
        </>
      ) : p.image ? (
        <Person src={p.image} side="right" />
      ) : null}

      <div style={{position: 'absolute', ...columnStyle}}>
        {align === 'left' ? (
          <div style={{width: 120, height: 14, borderRadius: 7, background: p.colors.highlight, marginBottom: 26}} />
        ) : null}
        {p.chip === 'maps_pin' ? (
          <div style={{marginBottom: 20}}>
            <MapsPinChip />
          </div>
        ) : null}
        <HighlightTitle lines={lines} size={size} highlight={p.highlight || ''} dark={!clean} highlightColor={p.colors.highlight} align={align} />
      </div>

      {layout === 'payment' && p.amount ? <PaymentCard amount={p.amount} /> : null}
      {layout === 'checklist' && p.items?.length ? <ChecklistCard items={p.items} accent={p.colors.highlight} /> : null}

      {p.logo ? (
        <Img src={staticFile(p.logo)} style={{position: 'absolute', left: 64, bottom: 40, height: 56, width: 'auto', opacity: 0.95}} />
      ) : null}
    </AbsoluteFill>
  );
};
