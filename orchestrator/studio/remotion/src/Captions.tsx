import React from "react";
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {POP, theme} from "./theme";
import type {Word} from "./types";

const MAX_WORDS = 3;
const GAP = 0.35; // seconds of silence that starts a new page

// Words grouped into short pages (≤3 words, new page after a pause or a sentence end).
export const pages = (words: Word[]): Word[][] => {
  const out: Word[][] = [];
  for (const word of words) {
    const page = out[out.length - 1];
    const prev = page?.[page.length - 1];
    if (!page || page.length >= MAX_WORDS || word.start - prev!.end > GAP || /[.!?।]$/.test(prev!.text)) {
      out.push([word]);
    } else {
      page.push(word);
    }
  }
  return out;
};

// Hormozi-style captions: big, heavy, outlined; the word being said is yellow and pops.
export const Captions: React.FC<{words: Word[]}> = ({words}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const all = pages(words);
  const index = all.findIndex((page, n) => t >= page[0].start && t < (all[n + 1]?.[0].start ?? page[page.length - 1].end + 0.6));
  if (index < 0) return null;
  const page = all[index];
  const pageIn = spring({frame: frame - Math.round(page[0].start * fps), fps, config: POP});
  return (
    <AbsoluteFill style={{justifyContent: "flex-end", alignItems: "center", paddingBottom: theme.safeBottom,
      paddingLeft: theme.side, paddingRight: theme.side}}>
      <div style={{display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "0 34px",
        transform: `scale(${interpolate(pageIn, [0, 1], [0.85, 1])})`, opacity: Math.min(1, pageIn * 2)}}>
        {page.map((word, n) => {
          const active = t >= word.start && t < word.end + 0.05;
          const hit = spring({frame: frame - Math.round(word.start * fps), fps, config: POP});
          return (
            <span key={n} style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 92, lineHeight: 1.15,
              textTransform: "uppercase", color: active ? theme.accent : theme.text,
              WebkitTextStroke: "14px #000", paintOrder: "stroke fill",
              textShadow: "0 10px 30px rgba(0,0,0,0.6)",
              transform: `scale(${active ? interpolate(hit, [0, 1], [1.18, 1.06]) : 1})`,
              display: "inline-block", transformOrigin: "center bottom"}}>
              {word.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
