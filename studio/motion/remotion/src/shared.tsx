import React, {useEffect, useState} from 'react';
import {continueRender, delayRender, staticFile} from 'remotion';

export type Colors = {
  primary: string;
  accent: string;
  text: string;
  background: string;
  highlight: string;
};

export type BaseProps = {
  width: number;
  height: number;
  durationInFrames: number;
  fps: number;
  colors: Colors;
  fontTitle?: string;
  placement?: 'overlay' | 'behind';
};

export const defaultColors: Colors = {
  primary: '#FFD400',
  accent: '#FFFFFF',
  text: '#FFFFFF',
  background: '#0B0B0F',
  highlight: '#FFD400',
};

const FONTS: [string, string, number][] = [
  ['Montserrat', 'fonts/Montserrat-Black.otf', 900],
  ['Montserrat', 'fonts/Montserrat-ExtraBold.otf', 800],
  ['Montserrat', 'fonts/Montserrat-Bold.otf', 700],
  ['Montserrat', 'fonts/Montserrat-SemiBold.otf', 600],
  ['Montserrat', 'fonts/Montserrat-Medium.otf', 500],
  ['Inter', 'fonts/Inter.ttf', 400],
  ['DM Serif Display', 'fonts/DMSerifDisplay.ttf', 400],
];
export const serifFamily = '"DM Serif Display", Georgia, serif';
// Variable fonts cover a weight range in one file.
const VARIABLE_FONTS: [string, string][] = [['Outfit', 'fonts/Outfit.ttf']];

let fontsPromise: Promise<void> | null = null;

/** Load the bundled fonts before the first frame renders (no network needed) and set the
 * brand's title font (props.fontTitle, e.g. "Outfit") as --title-font. */
export const useFonts = (titleFont?: string) => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  if (typeof document !== 'undefined') {
    const fam = (titleFont || 'Montserrat').split(/\s+(?:Thin|Light|Regular|Medium|SemiBold|Bold|ExtraBold|Black)$/i)[0];
    document.documentElement.style.setProperty('--title-font', `"${fam}", Montserrat, Inter, Arial, sans-serif`);
  }
  useEffect(() => {
    if (!fontsPromise) {
      fontsPromise = Promise.all([
        ...FONTS.map(([family, file, weight]) =>
          new FontFace(family, `url(${staticFile(file)})`, {weight: String(weight)}).load().then((f) => {
            document.fonts.add(f);
          })),
        ...VARIABLE_FONTS.map(([family, file]) =>
          new FontFace(family, `url(${staticFile(file)})`, {weight: '100 900'}).load().then((f) => {
            document.fonts.add(f);
          })),
      ]).then(() => undefined);
    }
    fontsPromise.then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

export const unit = (p: BaseProps) => Math.min(p.width, p.height) / 1080;

export const titleFamily = 'var(--title-font, Montserrat, Inter, Arial, sans-serif)';

/** Soft, layered shadow that reads as real depth rather than a flat drop shadow. */
export const depthShadow = (u: number, strength = 1) =>
  [
    `0 ${2 * u}px ${2 * u}px rgba(0,0,0,${0.28 * strength})`,
    `0 ${8 * u}px ${16 * u}px rgba(0,0,0,${0.32 * strength})`,
    `0 ${24 * u}px ${48 * u}px rgba(0,0,0,${0.38 * strength})`,
  ].join(', ');

export const withAlpha = (hex: string, alpha: number) => {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
};

/** White or near-black text, whichever reads better on `hex`. */
export const readableOn = (hex: string) => {
  const h = hex.replace('#', '');
  const lin = (i: number) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin(0) + 0.7152 * lin(2) + 0.0722 * lin(4);
  return L > 0.45 ? '#0B0B0F' : '#FFFFFF';
};

/** Caption band (share of frame height from the bottom) that graphics must keep clear of. */
export const captionClearance = (p: BaseProps) => (p.height > p.width ? 0.36 : 0.18);

export const Fill: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div style={{position: 'absolute', inset: 0, ...style}}>{children}</div>
);
