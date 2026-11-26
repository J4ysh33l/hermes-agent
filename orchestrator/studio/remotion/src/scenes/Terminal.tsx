import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {Arrive} from "../motion";
import {useTheme} from "../theme";
import type {TerminalScene} from "../types";

const TYPE_FRAMES = 2; // per character of a command
// A terminal is dark in every theme, so its text has its own colours (a paper theme's ink would vanish).
const INK = {command: "#e6e9ef", output: "#8a93a6", prompt: "#3ddc97"};

// A terminal: "$ " lines type themselves one after another, output lines print instantly after.
export const Terminal: React.FC<{scene: TerminalScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const cost = scene.lines.map((l) => (l.startsWith("$") ? l.length * TYPE_FRAMES + 8 : 4));
  const total = cost.reduce((a, b) => a + b, 0);
  const scale = Math.min(1, (frames * 0.75) / Math.max(1, total)); // always finish by 75% of the scene
  let at = 6;
  const rows = scene.lines.map((line, n) => {
    const start = at;
    at += cost[n] * scale;
    const isCommand = line.startsWith("$");
    const shown = isCommand
      ? Math.floor(interpolate(frame, [start, start + line.length * TYPE_FRAMES * scale], [0, line.length],
        {extrapolateLeft: "clamp", extrapolateRight: "clamp"}))
      : frame >= start ? line.length : 0;
    if (frame < start) return null;
    return (
      <div key={n} style={{color: isCommand ? INK.command : INK.output, minHeight: "1.4em"}}>
        {isCommand ? <span style={{color: INK.prompt}}>{line.slice(0, Math.min(1, shown))}</span> : null}
        {isCommand ? line.slice(1, shown) : line.slice(0, shown)}
      </div>
    );
  });
  return (
    <Arrive enter="rise" style={{background: "#0a0c10", borderRadius: 24, overflow: "hidden",
      boxShadow: "0 40px 120px rgba(0,0,0,0.55)", border: `2px solid ${theme.muted}33`}}>
      <div style={{padding: "18px 26px", fontFamily: theme.monoFamily, fontSize: 28, color: "#8a93a6",
        background: "#151922"}}>
        {scene.title || "terminal"}
      </div>
      <div style={{padding: "28px 32px", fontFamily: theme.monoFamily, fontSize: 42, lineHeight: 1.45,
        whiteSpace: "pre-wrap", wordBreak: "break-word"}}>
        {rows}
        <span style={{color: theme.accent, opacity: Math.floor(frame / 8) % 2 ? 0 : 1}}>▌</span>
      </div>
    </Arrive>
  );
};
