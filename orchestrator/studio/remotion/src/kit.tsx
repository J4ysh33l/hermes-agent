// Motion and marks shared by the faceless shorts (Short.tsx) and the edits of your own footage (edit/):
// one way to reveal type, strike a claim, tick a row and land a number, so both read as the same hand.
import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";

// Confident arrivals: fast, then settling (the ease-out-expo of the design system).
export const settle = Easing.bezier(0.16, 1, 0.3, 1);

// 0 → 1 over `frames` from `at`, eased.
export const ramp = (frame: number, at: number, frames: number, easing = settle) =>
  interpolate(frame, [at, at + frames], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing});

// A line of type rising out of a mask (the text is clipped below its own baseline until it arrives).
export const Rise: React.FC<{at?: number; frames?: number; style?: React.CSSProperties; children: React.ReactNode}> =
  ({at = 0, frames = 14, style, children}) => {
    const frame = useCurrentFrame();
    const p = ramp(frame, at, frames);
    return (
      <div style={{overflow: "hidden", paddingBottom: "0.12em", marginBottom: "-0.12em", ...style}}>
        <div style={{transform: `translateY(${(1 - p) * 110}%)`, opacity: p > 0 ? 1 : 0}}>{children}</div>
      </div>
    );
  };

// "the *real* fix" → the starred words set apart (the brand's accent word: italic, in the accent colour).
export const Marked: React.FC<{text: string; accent: string; italic?: boolean}> = ({text, accent, italic = true}) => (
  <>
    {text.split(/(\*[^*]+\*)/).map((part, n) =>
      part.startsWith("*") && part.endsWith("*") && part.length > 2
        ? <span key={n} style={{color: accent, fontStyle: italic ? "italic" : "normal"}}>{part.slice(1, -1)}</span>
        : <React.Fragment key={n}>{part}</React.Fragment>)}
  </>
);

export const plain = (text: string) => text.replace(/\*/g, "");

// A marker stroke through the text, drawn left to right from `at` (a slight rise, round ends).
export const Strike: React.FC<{at?: number; colour: string; thick?: number}> = ({at, colour, thick = 8}) => {
  const frame = useCurrentFrame();
  if (at === undefined) return null;
  const p = ramp(frame, at, 9, Easing.inOut(Easing.cubic));
  return (
    <svg viewBox="0 0 100 20" preserveAspectRatio="none" style={{position: "absolute", left: "-3%", width: "106%", top: "34%",
      height: "34%", overflow: "visible", pointerEvents: "none"}}>
      <path d="M1 13 C 30 11, 60 9, 99 6" fill="none" stroke={colour} strokeWidth={thick} strokeLinecap="round"
        vectorEffect="non-scaling-stroke" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - p} />
    </svg>
  );
};

// An underline drawn under the text from `at`.
export const Underline: React.FC<{at?: number; colour: string; thick?: number}> = ({at, colour, thick = 7}) => {
  const frame = useCurrentFrame();
  if (at === undefined) return null;
  const p = ramp(frame, at, 10);
  return <div style={{position: "absolute", left: 0, bottom: -thick, height: thick, width: "100%", background: colour,
    borderRadius: thick, transform: `scaleX(${p})`, transformOrigin: "left"}} />;
};

// A tick or a cross that draws itself from `at`.
export const Tick: React.FC<{at: number; kind: "check" | "cross"; colour: string; size: number}> = ({at, kind, colour, size}) => {
  const frame = useCurrentFrame();
  const p = ramp(frame, at, 10);
  const q = ramp(frame, at + 4, 10);
  const line = {fill: "none", stroke: colour, strokeWidth: 3.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
    pathLength: 1, strokeDasharray: 1};
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{flexShrink: 0, transform: `scale(${0.85 + 0.15 * p})`}}>
      <circle cx={12} cy={12} r={10.5} fill={colour} opacity={0.16 * p} />
      {kind === "check"
        ? <path d="M7 12.5 l3.2 3.2 L17 8.6" {...line} strokeDashoffset={1 - p} />
        : <>
            <path d="M8 8 L16 16" {...line} strokeDashoffset={1 - p} />
            <path d="M16 8 L8 16" {...line} strokeDashoffset={1 - q} />
          </>}
    </svg>
  );
};

// A number counting to `to` from `at` (fast, then easing), landing exactly on it.
export const useCount = (from: number, to: number, at: number, frames = 26) => {
  const frame = useCurrentFrame();
  const k = ramp(frame, at, frames, Easing.out(Easing.exp));
  return frame >= at + frames ? to : from + (to - from) * k;
};

// Width estimate for one line of type at weight 600 (share of the font size per character), to size a line
// so it never wraps: errs wide, never overflows.
export const fitLine = (text: string, size: number, width: number, advance = 0.5) => {
  const t = plain(text);
  const units = [...t].reduce((n, c) => n + (/[iIl1.,:;'!|]/.test(c) ? 0.28 : /[MWmw@%₹]/.test(c) ? 0.86 : /[A-Z0-9]/.test(c) ? 0.6 : c === " " ? 0.24 : advance), 0);
  return Math.min(size, Math.floor(width / Math.max(1, units)));
};
