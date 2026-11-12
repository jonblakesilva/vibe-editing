import {useEffect, useState} from 'react';
import {continueRender, delayRender, staticFile} from 'remotion';

let headlinePromise: Promise<void> | null = null;

/** Loads the bundled Anton font (a free Google font already vendored in this repo's
 * caption-clips fonts, copied into public/fonts/ here) for the big thumbnail headline.
 * The reference thumbnails (Kai Stone, Keaton Walker, GHL tutorials) all use a heavy
 * condensed display face for 2-4 word titles -- something the brand's own title font
 * (e.g. Outfit) isn't. Loaded from the local file, never fetched over the network. */
export const useHeadlineFont = () => {
  const [handle] = useState(() => delayRender('Loading thumbnail headline font'));
  useEffect(() => {
    if (!headlinePromise) {
      headlinePromise = new FontFace('Anton', `url(${staticFile('fonts/Anton.ttf')})`, {weight: '400'})
        .load()
        .then((f) => {
          document.fonts.add(f);
        })
        .then(() => undefined);
    }
    headlinePromise.then(() => continueRender(handle)).catch(() => continueRender(handle));
  }, [handle]);
};

export const headlineFamily = '"Anton", "Montserrat", Impact, Haettenschweiler, sans-serif';
