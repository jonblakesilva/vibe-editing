import React from 'react';
import {readableOn} from '../../shared';
import {headlineFamily} from './fonts';

const MONEY_RE = /^\$\d/;

/** Renders title lines that have already been wrapped and sized by the Python side's
 * `fit_title` helper (studio/thumbnail.py) -- this component never re-wraps or re-sizes,
 * it only decides colour per word: exactly the words in `highlight` sit on a solid
 * highlight box (rule: "exactly ONE phrase sits on a solid highlight box"), any other
 * money-looking word (e.g. "$297.00") goes green, everything else is plain white/black
 * depending on `dark`. */
export const HighlightTitle: React.FC<{
  lines: string[];
  size: number;
  highlight: string;
  dark: boolean;
  highlightColor: string;
  align?: 'left' | 'center';
}> = ({lines, size, highlight, dark, highlightColor, align = 'left'}) => {
  const hi = new Set((highlight || '').toUpperCase().split(/\s+/).filter(Boolean));
  const base = dark ? '#FFFFFF' : '#14110F';
  const boxText = readableOn(highlightColor);
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: align === 'center' ? 'center' : 'flex-start'}}>
      {lines.map((line, li) => (
        <div
          key={li}
          style={{
            fontFamily: headlineFamily,
            fontWeight: 400,
            fontSize: size,
            lineHeight: 1.06,
            display: 'flex',
            flexWrap: 'nowrap',
            justifyContent: align === 'center' ? 'center' : 'flex-start',
          }}
        >
          {line
            .split(/\s+/)
            .filter(Boolean)
            .map((w, i, arr) => {
              const key = w.replace(/[^\w$%.,+]/g, '');
              const isHi = hi.has(key) || hi.has(w);
              const isMoney = !isHi && MONEY_RE.test(key);
              return (
                <span
                  key={i}
                  style={{
                    color: isHi ? boxText : isMoney ? '#22C55E' : base,
                    background: isHi ? highlightColor : 'transparent',
                    padding: isHi ? '2px 16px' : 0,
                    marginRight: i < arr.length - 1 ? (isHi ? 10 : 14) : 0,
                    borderRadius: isHi ? 6 : 0,
                    boxShadow: isHi ? '0 7px 0 rgba(0,0,0,0.22)' : 'none',
                    textShadow: isHi
                      ? 'none'
                      : dark
                        ? '0 5px 0 rgba(0,0,0,0.38), 0 12px 28px rgba(0,0,0,0.5)'
                        : '0 2px 0 rgba(0,0,0,0.12)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {w}
                </span>
              );
            })}
        </div>
      ))}
    </div>
  );
};
