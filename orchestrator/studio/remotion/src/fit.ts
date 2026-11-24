// Text that must fit a width without wrapping (a caption word, a stat's value): its size from an estimate of
// how wide the font draws it. An estimate, not a measurement: it errs wide, so text may shrink a little
// early but never overflows. Average advance per character at weight 800–900, as a share of the font size.
import {FONTS} from "./theme";

const ADVANCE: Record<keyof typeof FONTS, {lower: number; upper: number}> = {
  inter: {lower: 0.6, upper: 0.74},
  montserrat: {lower: 0.66, upper: 0.82},
  anton: {lower: 0.46, upper: 0.52},
  jetbrains: {lower: 0.62, upper: 0.62},
};

const NARROW = /[iIl1.,:;'!|]/g;
const WIDE = /[MWmw@%₹$€£]/g;

// Width in px of `text` at `size`, `upper` = shown in capitals.
export const textWidth = (text: string, size: number, font: keyof typeof FONTS, upper = false) => {
  const shown = upper ? text.toUpperCase() : text;
  const capitals = upper ? shown.length : (shown.match(/[A-Z0-9]/g) ?? []).length;
  const {lower, upper: cap} = ADVANCE[font];
  const narrow = (shown.match(NARROW) ?? []).length;
  const wide = (shown.match(WIDE) ?? []).length;
  const units = capitals * cap + (shown.length - capitals) * lower - narrow * 0.3 + wide * 0.25;
  return Math.max(0, units) * size;
};

// The largest size ≤ `size` at which `text` fits `width` px on one line (`extra` px of outline etc. per side).
export const fitSize = (text: string, size: number, width: number, font: keyof typeof FONTS, upper = false,
  extra = 0) => {
  const wide = textWidth(text, size, font, upper) + 2 * extra;
  return wide <= width ? size : Math.floor((size * (width - 2 * extra)) / Math.max(1, wide - 2 * extra));
};
