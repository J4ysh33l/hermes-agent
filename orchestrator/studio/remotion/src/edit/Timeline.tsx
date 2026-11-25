// The whole edit's overlay in one transparent render: every graphic and scene at its time, and the captions
// (word by word, the spoken word in a box). ffmpeg lays it over the cut footage once (render.py).
import React from "react";
import {AbsoluteFill, Sequence, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {EditItem, EditLook, FAMILIES, Graphic} from "./Graphic";
import {Scene, SceneItem, SEAM} from "./Scenes";

export type CaptionLook = {
  font: string;
  size: number;
  case: "sentence" | "lower" | "upper";
  colour: string;
  active: string; // the spoken word's box (mode box) or colour (mode colour)
  mode: "box" | "colour" | "plain";
  box_text: string;
  shadow: number;
  y: number;
  problem: string;
  solution: string;
};

export type CapWord = {text: string; from: number; to: number; tone?: "problem" | "solution"};
export type CapPage = {from: number; to: number; place: "face" | "seam" | "scene"; words: CapWord[]};
export type TimedItem = (EditItem | SceneItem) & {from: number; frames: number};

export type TimelineProps = {
  look: EditLook & {handle?: string};
  captions: CaptionLook;
  items: TimedItem[];
  pages: CapPage[];
  frames: number;
};

const Page: React.FC<{cap: CaptionLook; page: CapPage}> = ({cap, page}) => {
  const frame = useCurrentFrame(); // from the page's start
  const {fps} = useVideoConfig();
  const p = spring({frame, fps, config: {damping: 16, stiffness: 260, mass: 0.5}});
  const y = page.place === "seam" ? SEAM + 70 : page.place === "scene" ? 1560 : Math.round(cap.y * 1920);
  const now = frame + page.from;
  const chars = page.words.reduce((n, w) => n + w.text.length + 1, 0);
  const size = Math.round(cap.size * Math.min(1, 24 / Math.max(1, chars)));  // one line, always
  return (
    <AbsoluteFill>
      <div style={{position: "absolute", left: 50, right: 50, top: y - size, display: "flex",
        justifyContent: "center", flexWrap: "nowrap", gap: "4px 10px", transform: `scale(${0.9 + 0.1 * p})`, opacity: Math.min(1, p * 2)}}>
        {page.words.map((w, n) => {
          const next = page.words[n + 1]?.from ?? page.to;
          const on = now >= w.from && now < next;
          const tone = w.tone === "problem" ? cap.problem : w.tone === "solution" ? cap.solution : undefined;
          const boxed = cap.mode === "box" && on;
          const colour = boxed ? cap.box_text : cap.mode === "colour" && on ? cap.active : tone ?? cap.colour;
          const text = cap.case === "lower" ? w.text.toLowerCase() : cap.case === "upper" ? w.text.toUpperCase() : w.text;
          return (
            <span key={n} style={{fontFamily: FAMILIES[cap.font] ?? FAMILIES.poppins, fontWeight: 700, fontSize: size, lineHeight: 1.25, whiteSpace: "nowrap",
              color: colour, padding: "0 14px 4px", borderRadius: 14, background: boxed ? (tone ?? cap.active) : "transparent",
              textShadow: boxed ? "none" : `0 ${cap.shadow}px ${cap.shadow * 3}px rgba(0,0,0,0.65)`,
              transform: boxed ? "scale(1.06)" : "none"}}>{text}</span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const Timeline: React.FC<TimelineProps> = ({look, captions, items, pages}) => (
  <AbsoluteFill style={{backgroundColor: "transparent"}}>
    {items.map((it, n) => (
      <Sequence key={`g${n}`} from={it.from} durationInFrames={Math.max(1, it.frames)} layout="none">
        {it.kind === "scene"
          ? <Scene look={look} item={it as SceneItem} frames={it.frames} />
          : <Graphic look={look} item={it as EditItem} frames={it.frames} />}
      </Sequence>
    ))}
    {pages.map((page, n) => (
      <Sequence key={`c${n}`} from={page.from} durationInFrames={Math.max(1, page.to - page.from)} layout="none">
        <Page cap={captions} page={page} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
