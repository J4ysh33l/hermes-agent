import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {Arrive} from "../motion";
import {fitSize} from "../fit";
import {SAFE, useTheme} from "../theme";
import type {StatScene} from "../types";

const format = (n: number, decimals: number) =>
  n.toLocaleString("en-IN", {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

// One big number counting up (fast, then easing), a gentle pulse once it lands, the label underneath.
export const Stat: React.FC<{scene: StatScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const decimals = Number.isInteger(scene.value) ? 0 : 1;
  const landed = Math.min(36, frames * 0.6);
  // sized for the final value, so the count-up never changes size or wraps ("500M kg" stays on one line)
  const size = fitSize(`${scene.prefix}${format(scene.value, decimals)}${scene.suffix}`, 230, 1080 - 2 * SAFE.side,
    theme.font, false, 20);
  // Easing.exp ends at 99.9% (2^-10 short), so 1000 would land on 999: the last frames show the value itself
  const value = frame >= landed ? scene.value : interpolate(frame, [0, landed], [0, scene.value], {
    extrapolateRight: "clamp", easing: Easing.out(Easing.exp)});
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 30}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: size, lineHeight: 1, color: theme.accent,
        whiteSpace: "nowrap",
        transform: `scale(${frame >= landed ? 1 + 0.04 * Math.sin(frame / 6) : 1})`,
        textShadow: `0 0 80px ${theme.accent}55`}}>
        {scene.prefix}{format(value, decimals)}{scene.suffix}
      </div>
      <Arrive delay={10} enter="rise" style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 64,
        color: theme.text, lineHeight: 1.2}}>
        {scene.label}
      </Arrive>
    </div>
  );
};
