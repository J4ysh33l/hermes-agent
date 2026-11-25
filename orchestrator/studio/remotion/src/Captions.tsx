import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {FEELS} from "./motion";
import {fitSize} from "./fit";
import {CaptionStyle, FONTS, SAFE, useProfile, useTheme} from "./theme";
import type {Word} from "./types";

const GAP = 0.35; // seconds of silence that starts a new page
const HARD = /[.!?।]["')]*$/; // a sentence ends: always a new page
const SOFT = /[,;:—–]["')]*$/; // a clause ends: a new page if this one has 2+ words
// Words a page should not end on: they belong with the word after them.
const WEAK = new Set(["a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "and", "or", "but", "is",
  "my", "your", "our", "its", "their", "this", "that", "from", "as", "ka", "ki", "ke", "ko", "se", "ne", "aur"]);
const bare = (word: Word) => word.text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

// The narration in phrases: broken at sentence ends, pauses and (when it has 2+ words) commas.
const phrases = (words: Word[]): Word[][] => {
  const out: Word[][] = [];
  for (const word of words) {
    const phrase = out[out.length - 1];
    const prev = phrase?.[phrase.length - 1];
    const broken = !phrase || word.start - prev!.end > GAP || HARD.test(prev!.text) ||
      (SOFT.test(prev!.text) && phrase.length >= 2);
    if (broken) out.push([word]);
    else phrase.push(word);
  }
  return out;
};

// What a page of `size` words costs: every page costs 1 (fewer, fuller pages); a lone word, a page ending on
// "the", "of", "to"... (it belongs with the next word) and a page over `most` cost more; a page ending on a
// comma costs less (a natural break).
const pageCost = (phrase: Word[], from: number, size: number, most: number) => {
  const last = phrase[from + size - 1];
  const final = from + size === phrase.length;
  return 1 + (size === 1 && phrase.length > 1 ? 3 : 0) + (!final && WEAK.has(bare(last)) ? 4 : 0) +
    Math.max(0, size - most) * 2 + 0.3 * (most - Math.min(size, most)) ** 2 - (!final && SOFT.test(last.text) ? 1 : 0);
};

// How many words on each page of one phrase: the cheapest split (pages of 1 to most + 1 words), e.g.
// "Save the world today." at 3 a page → one page of 4, not "Save the | world today." or "... | today."
const sizes = (phrase: Word[], most: number): number[] => {
  const n = phrase.length;
  const best: {cost: number; size: number}[] = Array.from({length: n + 1}, () => ({cost: Infinity, size: 0}));
  best[n] = {cost: 0, size: 0};
  for (let from = n - 1; from >= 0; from--) {
    for (let size = 1; size <= Math.min(most + 1, n - from); size++) {
      const cost = pageCost(phrase, from, size, most) + best[from + size].cost;
      if (cost < best[from].cost) best[from] = {cost, size};
    }
  }
  const out: number[] = [];
  for (let at = 0; at < n; at += best[at].size) out.push(best[at].size);
  return out;
};

// Words grouped into caption pages.
export const pages = (words: Word[], most: number): Word[][] =>
  phrases(words).flatMap((phrase) => {
    let at = 0;
    return sizes(phrase, most).map((size) => phrase.slice(at, (at += size)));
  });

// The caption size for a page: the profile's, smaller when its longest word would not fit the width or the
// page would take more than two lines.
const WIDTH = 1080 - 2 * SAFE.side;
export const pageSize = (page: Word[], captions: CaptionStyle) => {
  const fit = (text: string, width: number) => fitSize(text, captions.size * 1.04, width, captions.font,
    captions.upper, captions.stroke) / 1.04; // the word being said is drawn 4% larger
  const longest = Math.min(...page.map((w) => fit(w.text, WIDTH)));
  const whole = fit(page.map((w) => w.text).join("  "), WIDTH * 2 * 0.92);
  return Math.max(40, Math.floor(Math.min(captions.size, longest, whole)));
};

// Hormozi-style captions: big, heavy, outlined. The word being said is in the accent and pops;
// *emphasised* words stay in the second accent.
export const Captions: React.FC<{words: Word[]}> = ({words}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {captions, motion} = useProfile();
  const theme = useTheme();
  const t = frame / fps;
  const all = pages(words, captions.words);
  const index = all.findIndex((page, n) => t >= page[0].start && t < (all[n + 1]?.[0].start ?? page[page.length - 1].end + 0.6));
  if (index < 0) return null;
  const page = all[index];
  const feel = FEELS[motion.feel === "settle" ? "soft" : motion.feel];
  const size = pageSize(page, captions);
  const pageIn = spring({frame: frame - Math.round(page[0].start * fps), fps, config: feel});
  return (
    <AbsoluteFill style={{justifyContent: "flex-end", alignItems: "center", paddingBottom: SAFE.bottom,
      paddingLeft: SAFE.side, paddingRight: SAFE.side}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `0 ${size * 0.5}px`,
        transform: `scale(${interpolate(pageIn, [0, 1], [0.85, 1])})`, opacity: Math.min(1, pageIn * 2)}}>
        {page.map((word, n) => {
          // One word at a time: a word stays lit until the next one starts (two lit, enlarged words touched).
          const until = n + 1 < page.length ? page[n + 1].start : word.end + 0.3;
          const active = t >= word.start && t < until;
          const hit = spring({frame: frame - Math.round(word.start * fps), fps, config: feel});
          return (
            <span key={n} style={{fontFamily: FONTS[captions.font], fontWeight: 900, fontSize: size,
              lineHeight: 1.15, textTransform: captions.upper ? "uppercase" : "none",
              color: active ? theme.accent : word.emphasis ? theme.cool : captions.fill,
              WebkitTextStroke: `${captions.stroke}px ${captions.outline}`, paintOrder: "stroke fill",
              textShadow: `0 10px 30px ${captions.outline}99`, display: "inline-block", transformOrigin: "center bottom",
              transform: `scale(${active ? interpolate(hit, [0, 1], [1.1, 1.04]) : 1})`}}>
              {word.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
