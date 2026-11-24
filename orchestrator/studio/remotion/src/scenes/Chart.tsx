import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {Arrive, revealAt, usePop} from "../motion";
import {useTheme} from "../theme";
import type {ChartScene} from "../types";

const W = 900;
const H = 760;
const fmt = (v: number) => (Number.isInteger(v) ? v.toLocaleString("en-IN") : v.toFixed(1));

// Bars grow one by one (on their sentences when the narration has one each), or a line draws itself;
// the highlighted value (the largest by default) is in the accent.
export const Chart: React.FC<{scene: ChartScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const max = Math.max(...scene.values, 0) || 1;
  const hot = scene.highlight >= 0 ? scene.highlight : scene.values.indexOf(Math.max(...scene.values));
  const n = scene.values.length;
  const title = scene.title ? (
    <Arrive style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 76, color: theme.text, marginBottom: 40}}>
      {scene.title}
    </Arrive>
  ) : null;
  if (scene.kind === "line") {
    const pts = scene.values.map((v, i) => [40 + (i * (W - 80)) / Math.max(1, n - 1), H - 120 - ((H - 220) * v) / max]);
    const path = pts.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
    const draw = interpolate(frame, [8, Math.max(9, frames * 0.6)], [0, 1], {extrapolateLeft: "clamp",
      extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic)});
    const length = pts.slice(1).reduce((sum, [x, y], i) => sum + Math.hypot(x - pts[i][0], y - pts[i][1]), 0);
    return (
      <div>
        {title}
        <svg width={W} height={H}>
          <path d={path} fill="none" stroke={theme.accent} strokeWidth={12} strokeLinecap="round" strokeLinejoin="round"
            strokeDasharray={length} strokeDashoffset={length * (1 - draw)} />
          {pts.map(([x, y], i) => {
            const on = draw >= i / Math.max(1, n - 1);
            return (
              <g key={i} opacity={on ? 1 : 0}>
                <circle cx={x} cy={y} r={i === hot ? 22 : 14} fill={i === hot ? theme.accent : theme.text} />
                <text x={x} y={y - 40} textAnchor="middle" fontFamily={theme.sans} fontWeight={900} fontSize={44}
                  fill={i === hot ? theme.accent : theme.text}>{fmt(scene.values[i])}{scene.suffix}</text>
                <text x={x} y={H - 50} textAnchor="middle" fontFamily={theme.sans} fontWeight={700} fontSize={34}
                  fill={theme.muted}>{scene.labels[i]}</text>
              </g>
            );
          })}
        </svg>
      </div>
    );
  }
  const gap = 28;
  const bar = (W - gap * (n - 1)) / n;
  return (
    <div>
      {title}
      <div style={{display: "flex", alignItems: "flex-end", gap, height: H}}>
        {scene.values.map((v, i) => (
          <Bar key={i} delay={revealAt(i, n, frames, scene.beats)} width={bar} height={((H - 160) * v) / max}
            value={`${fmt(v)}${scene.suffix}`} label={scene.labels[i]} hot={i === hot} />
        ))}
      </div>
    </div>
  );
};

const Bar: React.FC<{delay: number; width: number; height: number; value: string; label: string; hot: boolean}> = (
  {delay, width, height, value, label, hot},
) => {
  const theme = useTheme();
  const grow = usePop(delay);
  const colour = hot ? theme.accent : theme.cool;
  return (
    <div style={{width, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end",
      height: "100%"}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: width > 200 ? 52 : 40, color: colour,
        opacity: grow, marginBottom: 12}}>{value}</div>
      <div style={{width: "100%", height: Math.max(0, height * grow), background: colour, borderRadius: "16px 16px 4px 4px",
        opacity: hot ? 1 : 0.75}} />
      <div style={{fontFamily: theme.sans, fontWeight: 700, fontSize: width > 200 ? 36 : 28, color: theme.muted,
        marginTop: 16, textAlign: "center", height: 80}}>{label}</div>
    </div>
  );
};
