import React from 'react';
import {Img, staticFile} from 'remotion';

/** The speaker cut-out, bled off the bottom edge and one side -- big, the way the
 * reference thumbnails (Kai Stone, Keaton Walker) crop a close head-and-shoulders shot,
 * never a small sticker floating in the middle. `heightPct` of ~100-110% matches the
 * "95-110% of frame height" rule; the Python side already crops to head-and-shoulders
 * (see `_face_crop_box` in studio/thumbnail.py), this just places and sizes it. */
export const Person: React.FC<{src: string; side: 'left' | 'right'; heightPct?: number; mirror?: boolean}> = ({
  src,
  side,
  heightPct = 104,
  mirror,
}) => (
  <Img
    src={staticFile(src)}
    style={{
      position: 'absolute',
      bottom: -6,
      [side]: -8,
      height: `${heightPct}%`,
      width: 'auto',
      maxWidth: '62%',
      objectFit: 'contain',
      objectPosition: `${side} bottom`,
      transform: mirror ? 'scaleX(-1)' : undefined,
      filter: 'drop-shadow(0 22px 34px rgba(0,0,0,0.55))',
    } as React.CSSProperties}
  />
);
