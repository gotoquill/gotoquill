import type { PDFFont } from 'pdf-lib';
import { textMetrics } from './text-metrics.js';

/** Visible bounds, including side bearings and only the descenders in this text. */
export function textBounds(text: string, font: PDFFont): number[] {
  const metrics = textMetrics[font.name];
  const boxes: number[][] = [];
  let advance = 0;
  for (const char of text) {
    const box = metrics?.[char];
    if (box) boxes.push([advance + box[0], box[1], advance + box[2], box[3]]);
    // pdf-lib draws a single Tj string, without pair-kerning adjustments.
    advance += font.widthOfTextAtSize(char, 1);
  }
  if (!boxes.length) return [0, -0.207, Math.max(font.widthOfTextAtSize(text, 1), 0.001), 0.718];
  return [Math.min(...boxes.map(b => b[0])), Math.min(...boxes.map(b => b[1])),
    Math.max(...boxes.map(b => b[2])), Math.max(...boxes.map(b => b[3]))];
}
