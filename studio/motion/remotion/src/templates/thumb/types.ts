export type ThumbLayout =
  | 'face-number'
  | 'payment'
  | 'checklist'
  | 'screenshot'
  | 'two-person'
  | 'clean-white'
  | 'shorts-cover';

export type ChecklistItem = {text: string; done: boolean};

/** Fractions (0-1) of the screenshot card's own width/height -- not the full canvas --
 * so the circle lands on the same spot regardless of how big the card is drawn. */
export type ScreenshotBox = {x: number; y: number; w: number; h: number};
