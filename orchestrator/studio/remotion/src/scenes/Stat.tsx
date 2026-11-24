import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {Arrive} from "../motion";
import {useTheme} from "../theme";
import type {StatScene} from "../types";

const format = (n: number, decimals: number) =>
  n.toLocaleString("en-IN", {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

// One big number counting up (fast, then easing), a gentle pulse once it lands, the label underneath.
export const Stat: React.FC<{scene: StatScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const decimals = Number.isInteger(scene.value) ? 0 : 1;
  const landed = Math.min(36, frames * 0.6);
  const value = interpolate(frame, [0, landed], [0, scene.value], {extrapolateRight: "clamp",
    easing: Easing.out(Easing.exp)});
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 30}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 230, lineHeight: 1, color: theme.accent,
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
