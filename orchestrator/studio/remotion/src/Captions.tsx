import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {FEELS} from "./motion";
import {FONTS, SAFE, useProfile, useTheme} from "./theme";
import type {Word} from "./types";

const GAP = 0.35; // seconds of silence that starts a new page

// Words grouped into short pages (≤ captions.words; a new page after a pause or a sentence end).
export const pages = (words: Word[], most: number): Word[][] => {
  const out: Word[][] = [];
  for (const word of words) {
    const page = out[out.length - 1];
    const prev = page?.[page.length - 1];
    if (!page || page.length >= most || word.start - prev!.end > GAP || /[.!?।]$/.test(prev!.text)) {
      out.push([word]);
    } else {
      page.push(word);
    }
  }
  return out;
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
  const feel = FEELS[motion.feel];
  const pageIn = spring({frame: frame - Math.round(page[0].start * fps), fps, config: feel});
  return (
    <AbsoluteFill style={{justifyContent: "flex-end", alignItems: "center", paddingBottom: SAFE.bottom,
      paddingLeft: SAFE.side, paddingRight: SAFE.side}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: `0 ${captions.size * 0.5}px`,
        transform: `scale(${interpolate(pageIn, [0, 1], [0.85, 1])})`, opacity: Math.min(1, pageIn * 2)}}>
        {page.map((word, n) => {
          // One word at a time: a word stays lit until the next one starts (two lit, enlarged words touched).
          const until = n + 1 < page.length ? page[n + 1].start : word.end + 0.3;
          const active = t >= word.start && t < until;
          const hit = spring({frame: frame - Math.round(word.start * fps), fps, config: feel});
          return (
            <span key={n} style={{fontFamily: FONTS[captions.font], fontWeight: 900, fontSize: captions.size,
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
