import React from "react";
import {interpolate} from "remotion";
import {revealAt, usePop} from "../motion";
import {theme} from "../theme";
import type {CompareScene, Side} from "../types";

// Two stacked cards (vertical video has no room side by side) with a VS badge between them.
export const Compare: React.FC<{scene: CompareScene; frames: number}> = ({scene, frames}) => {
  const vs = usePop(8);
  const count = scene.left.points.length + scene.right.points.length;
  return (
    <div style={{display: "flex", flexDirection: "column", gap: 0, alignItems: "stretch"}}>
      <Card side={scene.left} colour={theme.bad} from={-1} first={0} count={count} frames={frames} beats={scene.beats} />
      <div style={{alignSelf: "center", margin: "-26px 0", zIndex: 2, fontFamily: theme.sans, fontWeight: 900,
        fontSize: 54, color: theme.bg, background: theme.accent, borderRadius: 60, padding: "14px 34px",
        transform: `scale(${vs}) rotate(${interpolate(vs, [0, 1], [-30, 0])}deg)`}}>
        VS
      </div>
      <Card side={scene.right} colour={theme.good} from={1} first={scene.left.points.length} count={count}
        frames={frames} beats={scene.beats} />
    </div>
  );
};

interface CardProps {
  side: Side;
  colour: string;
  from: number;
  first: number;
  count: number;
  frames: number;
  beats: number[];
}

const Card: React.FC<CardProps> = ({side, colour, from, first, count, frames, beats}) => {
  const p = usePop(from < 0 ? 0 : 4);
  return (
    <div style={{background: theme.panel, borderRadius: 26, padding: "40px 40px", border: `4px solid ${colour}`,
      transform: `translateX(${interpolate(p, [0, 1], [from * 400, 0])}px)`, opacity: p}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 66, color: colour, marginBottom: 18}}>
        {side.label}
      </div>
      {side.points.map((point, n) => <Point key={n} text={point} delay={revealAt(first + n, count, frames, beats)} />)}
    </div>
  );
};

const Point: React.FC<{text: string; delay: number}> = ({text, delay}) => {
  const p = usePop(delay);
  return (
    <div style={{fontFamily: theme.sans, fontWeight: 600, fontSize: 48, color: theme.text, lineHeight: 1.3,
      opacity: p, transform: `translateY(${interpolate(p, [0, 1], [20, 0])}px)`}}>
      • {text}
    </div>
  );
};
