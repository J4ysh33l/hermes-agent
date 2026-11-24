// The motion building blocks. Any scene, any part of a scene, can use any of them:
// - FEELS: spring character (snappy / soft / bouncy)
// - ENTERS: how a thing arrives, as a style from progress 0 → 1
// - EXITS: how a scene leaves over its last frames
// - TRANSITIONS: scene to scene, the outgoing scene still moving under the incoming one
// - Camera: slow drift over the scene plus a punch-in on every *emphasised* word
// - Stepped: the "handmade" 12 fps look (graphics hold every other frame)
// Scenes ask for these by name; a storyboard can override them per scene; the profile sets defaults.
import React from "react";
import {AbsoluteFill, Easing, Freeze, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {Enter, Exit, Feel, SAFE, Transition, useProfile} from "./theme";

export const FEELS: Record<Feel, {damping: number; stiffness: number; mass: number}> = {
  snappy: {damping: 14, stiffness: 180, mass: 0.6},
  soft: {damping: 20, stiffness: 110, mass: 0.9},
  bouncy: {damping: 9, stiffness: 160, mass: 0.7},
};

type Style = React.CSSProperties;

export const ENTERS: Record<Enter, (p: number) => Style> = {
  pop: (p) => ({transform: `scale(${interpolate(p, [0, 1], [0.7, 1])})`, opacity: Math.min(1, p * 2),
    filter: `blur(${interpolate(p, [0, 1], [10, 0], {extrapolateRight: "clamp"})}px)`}),
  rise: (p) => ({transform: `translateY(${interpolate(p, [0, 1], [80, 0])}px)`, opacity: Math.min(1, p * 1.6)}),
  slide: (p) => ({transform: `translateX(${interpolate(p, [0, 1], [-160, 0])}px)`, opacity: Math.min(1, p * 1.6)}),
  drop: (p) => ({transform: `translateY(${interpolate(p, [0, 1], [-120, 0])}px) rotate(${interpolate(p, [0, 1], [-4, 0])}deg)`,
    opacity: Math.min(1, p * 2)}),
  zoom: (p) => ({transform: `scale(${interpolate(p, [0, 1], [1.6, 1])})`, opacity: Math.min(1, p * 1.4)}),
  fade: (p) => ({opacity: p}),
};

// `t` runs 0 → 1 over the scene's last exit_frames.
export const EXITS: Record<Exit, (t: number) => Style> = {
  lift: (t) => ({transform: `translateY(${-40 * t}px)`, opacity: 1 - t}),
  fade: (t) => ({opacity: 1 - t}),
  whip: (t) => ({transform: `translateX(${-900 * t * t}px)`, filter: `blur(${24 * t}px)`, opacity: 1 - t * 0.6}),
  zoom: (t) => ({transform: `scale(${1 + 0.6 * t})`, filter: `blur(${16 * t}px)`, opacity: 1 - t}),
  cut: () => ({}),
};

const W = 1080;
const H = 1920;
const hump = (t: number) => Math.sin(Math.PI * t); // 0 → 1 → 0 across a transition

// `t` runs 0 → 1 (eased) over the overlap: `out` styles the leaving scene, `in` the arriving one (drawn on top).
// "none" and "cut" do not overlap: SceneFrame uses the scene's own exit and entrance, or nothing.
export const TRANSITIONS: Record<Exclude<Transition, "none" | "cut">, {out: (t: number) => Style; in: (t: number) => Style}> = {
  fade: {out: (t) => ({opacity: 1 - t}), in: (t) => ({opacity: t})},
  push: {out: (t) => ({transform: `translateY(${-H * 0.6 * t}px)`, opacity: 1 - t * 0.8}),
    in: (t) => ({transform: `translateY(${H * 0.6 * (1 - t)}px)`, opacity: Math.min(1, t * 1.5)})},
  whip: {out: (t) => ({transform: `translateX(${-W * 1.2 * t}px)`, filter: `blur(${36 * hump(t)}px)`}),
    in: (t) => ({transform: `translateX(${W * 1.2 * (1 - t)}px)`, filter: `blur(${36 * hump(t)}px)`})},
  zoom: {out: (t) => ({transform: `scale(${1 + 1.4 * t})`, filter: `blur(${20 * t}px)`, opacity: 1 - t}),
    in: (t) => ({transform: `scale(${0.55 + 0.45 * t})`, filter: `blur(${14 * (1 - t)}px)`, opacity: Math.min(1, t * 1.4)})},
  flash: {out: (t) => ({opacity: t < 0.5 ? 1 : 0}), in: (t) => ({opacity: t < 0.5 ? 0 : 1})},
  burn: {out: (t) => ({opacity: 1 - t, filter: `brightness(${1 + 1.5 * t}) saturate(${1 + t})`}),
    in: (t) => ({opacity: t, filter: `brightness(${2.5 - 1.5 * t})`})},
};

// Drawn over both scenes during a transition: a white flash, or warm light sweeping across (film burn).
export const TRANSITION_LIGHT: Partial<Record<Transition, React.FC<{t: number}>>> = {
  flash: ({t}) => <AbsoluteFill style={{background: "#fff", opacity: 0.9 * hump(t)}} />,
  burn: ({t}) => (
    <AbsoluteFill style={{mixBlendMode: "screen", opacity: hump(t),
      background: `radial-gradient(ellipse 70% 55% at ${-20 + 140 * t}% ${70 - 40 * t}%, #fff8e0 0%, #ffb347 28%, #ff5e3a 52%, transparent 75%)`}} />
  ),
};

export const overlaps = (kind: Transition) => kind !== "none" && kind !== "cut";

export interface Passage {
  kind: Transition;
  frames: number; // the overlap (0 when the kind does not overlap)
}

const eased = (frame: number, from: number, frames: number) => interpolate(frame, [from, from + Math.max(1, frames)],
  [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic)});

export const usePop = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {motion} = useProfile();
  return spring({frame: frame - delay, fps, config: FEELS[motion.feel]});
};

// A part of a scene arriving `delay` frames in, with the scene's entrance (or its own).
export const Arrive: React.FC<{delay?: number; enter?: Enter; style?: Style; children: React.ReactNode}> = (
  {delay = 0, enter, style, children},
) => {
  const p = usePop(delay);
  const {motion} = useProfile();
  return <div style={{...style, ...ENTERS[enter ?? motion.enter](p)}}>{children}</div>;
};

const combine = (a: Style, b: Style): Style => ({
  ...a, ...b,
  transform: [a.transform, b.transform].filter(Boolean).join(" ") || undefined,
  filter: [a.filter, b.filter].filter(Boolean).join(" ") || undefined,
  opacity: (a.opacity === undefined ? 1 : Number(a.opacity)) * (b.opacity === undefined ? 1 : Number(b.opacity)),
});

// Holds every other frame when the profile asks for the 12 fps look.
export const Stepped: React.FC<{children: React.ReactNode}> = ({children}) => {
  const frame = useCurrentFrame();
  const {motion} = useProfile();
  if (!motion.step) return <>{children}</>;
  const every = Math.max(1, Math.round(30 / motion.step));
  return <Freeze frame={Math.floor(frame / every) * every}>{children}</Freeze>;
};

// A scene's frame: entrance (or the transition in), slow drift, exit (or the transition out, drawn in the
// `out.frames` past `frames` while the next scene arrives); padded into the safe area unless full-bleed.
export const SceneFrame: React.FC<{frames: number; enter?: Enter; exit?: Exit; into?: Passage; out?: Passage;
  fullBleed?: boolean; children: React.ReactNode}> = ({frames, enter, exit, into, out, fullBleed, children}) => {
  const frame = useCurrentFrame();
  const {motion} = useProfile();
  const p = usePop();
  const drift = 1 + interpolate(frame, [0, frames], [0, motion.drift], {extrapolateRight: "clamp"});
  const arriving = !into || into.kind === "none" ? ENTERS[enter ?? motion.enter](p)
    : into.kind === "cut" ? {} : TRANSITIONS[into.kind].in(eased(frame, 0, into.frames));
  const leaving = !out || out.kind === "none"
    ? EXITS[exit ?? motion.exit](interpolate(frame, [frames - motion.exit_frames, frames], [0, 1], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.in(Easing.cubic)}))
    : out.kind === "cut" ? {} : TRANSITIONS[out.kind].out(eased(frame, frames, out.frames));
  const style = combine(combine({transform: `scale(${drift})`}, arriving), leaving);
  return (
    <AbsoluteFill style={{...style, ...(fullBleed ? {} : {
      padding: `${SAFE.top}px ${SAFE.side}px ${SAFE.bottom + 260}px`, justifyContent: "center"})}}>
      <Stepped>{children}</Stepped>
    </AbsoluteFill>
  );
};

// The whole picture punches in on each emphasised word and eases back.
export const Camera: React.FC<{hits: number[]; children: React.ReactNode}> = ({hits, children}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {motion} = useProfile();
  let punch = 0;
  for (const at of hits) {
    const since = frame - Math.round(at * fps);
    if (since >= 0 && since < fps) {
      punch = Math.max(punch, interpolate(since, [0, 4, fps], [0, 1, 0], {easing: Easing.out(Easing.quad)}));
    }
  }
  return <AbsoluteFill style={{transform: `scale(${1 + motion.punch * punch})`}}>{children}</AbsoluteFill>;
};

// When item `index` of `count` appears: on the sentence that says it when the narration has a sentence
// per item (the last `count` sentences; any before them are the intro), else spread evenly.
export const revealAt = (index: number, count: number, frames: number, beats: number[] = [], fps = 30) =>
  beats.length >= count
    ? Math.max(4, Math.round(beats[beats.length - count + index] * fps) - 3)
    : Math.round(8 + (index * Math.max(0, frames * 0.7 - 8)) / Math.max(1, count));
