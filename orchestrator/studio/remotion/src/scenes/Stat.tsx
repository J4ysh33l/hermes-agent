import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {usePop} from "../motion";
import {theme} from "../theme";
import type {StatScene} from "../types";

const format = (n: number, decimals: number) =>
  n.toLocaleString("en-IN", {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

// One big number counting up (fast then easing), the label underneath.
export const Stat: React.FC<{scene: StatScene; frames: number}> = ({scene, frames}) => {
  const frame = useCurrentFrame();
  const label = usePop(10);
  const decimals = Number.isInteger(scene.value) ? 0 : 1;
  const value = interpolate(frame, [0, Math.min(36, frames * 0.6)], [0, scene.value], {
    extrapolateRight: "clamp", easing: Easing.out(Easing.exp),
  });
  const done = frame >= Math.min(36, frames * 0.6);
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 30}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 230, lineHeight: 1, color: theme.accent,
        transform: `scale(${done ? 1 + 0.04 * Math.sin(frame / 6) : 1})`,
        textShadow: `0 0 80px ${theme.accent}55`}}>
        {scene.prefix}{format(value, decimals)}{scene.suffix}
      </div>
      <div style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 64, color: theme.text, lineHeight: 1.2,
        opacity: label, transform: `translateY(${interpolate(label, [0, 1], [40, 0])}px)`}}>
        {scene.label}
      </div>
    </div>
  );
};
