import React from "react";
import {interpolate} from "remotion";
import {revealAt, usePop} from "../motion";
import {theme} from "../theme";
import type {BulletsScene} from "../types";

// Numbered list; items slide in spread over the narration so each lands near when it is said.
export const Bullets: React.FC<{scene: BulletsScene; frames: number}> = ({scene, frames}) => (
  <div style={{display: "flex", flexDirection: "column", gap: 34}}>
    {scene.title ? (
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 84, color: theme.text, marginBottom: 20}}>
        {scene.title}
      </div>
    ) : null}
    {scene.items.map((item, n) => (
      <Item key={n} n={n} text={item} delay={revealAt(n, scene.items.length, frames, scene.beats)} />
    ))}
  </div>
);

const Item: React.FC<{n: number; text: string; delay: number}> = ({n, text, delay}) => {
  const p = usePop(delay);
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 30, background: theme.panel, borderRadius: 22,
        padding: "28px 34px", borderLeft: `10px solid ${n % 2 ? theme.cool : theme.accent}`,
        transform: `translateX(${interpolate(p, [0, 1], [-120, 0])}px)`, opacity: Math.min(1, p * 1.5),
      }}
    >
      <div style={{fontFamily: theme.mono, fontSize: 52, color: n % 2 ? theme.cool : theme.accent}}>{n + 1}</div>
      <div style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 56, color: theme.text, lineHeight: 1.15}}>
        {text}
      </div>
    </div>
  );
};
