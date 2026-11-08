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
];

let fontsPromise: Promise<void> | null = null;

/** Load the bundled fonts before the first frame renders (no network needed). */
export const useFonts = () => {
  const [handle] = useState(() => delayRender('Loading fonts'));
  useEffect(() => {
    if (!fontsPromise) {
      fontsPromise = Promise.all(
        FONTS.map(([family, file, weight]) => {
          const face = new FontFace(family, `url(${staticFile(file)})`, {weight: String(weight)});
          return face.load().then((f) => {
            document.fonts.add(f);
          });
        }),
      ).then(() => undefined);
    }
    fontsPromise.then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

export const unit = (p: BaseProps) => Math.min(p.width, p.height) / 1080;

export const titleFamily = 'Montserrat, Inter, Arial, sans-serif';

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

export const Fill: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <div style={{position: 'absolute', inset: 0, ...style}}>{children}</div>
);
