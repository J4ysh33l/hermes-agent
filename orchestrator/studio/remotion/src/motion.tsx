// Shared motion: every scene enters with a punch-in and keeps a slow push so nothing sits still.
import React from "react";
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {POP, theme} from "./theme";

export const usePop = (delay = 0, config = POP) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config});
};

// Enter: scale 1.12 → 1, blur 12px → 0, opacity in 4 frames. Exit: last 5 frames fade and lift.
export const SceneFrame: React.FC<{frames: number; children: React.ReactNode}> = ({frames, children}) => {
  const frame = useCurrentFrame();
  const enter = usePop();
  const push = interpolate(frame, [0, frames], [1, 1.04], {extrapolateRight: "clamp"});
  const out = interpolate(frame, [frames - 5, frames], [1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.in(Easing.cubic),
  });
  const scale = interpolate(enter, [0, 1], [1.12, 1]) * push;
  const blur = interpolate(enter, [0, 1], [12, 0]);
  return (
    <AbsoluteFill
      style={{
        transform: `scale(${scale}) translateY(${(1 - out) * -40}px)`,
        filter: `blur(${blur}px)`,
        opacity: Math.min(1, frame / 4) * out,
        padding: `${theme.safeTop}px ${theme.side}px ${theme.safeBottom + 260}px`,
        justifyContent: "center",
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

// When item `index` of `count` appears: on the sentence that says it when the narration has a sentence
// per item (the last `count` sentences; any before them are the intro), else spread evenly.
export const revealAt = (index: number, count: number, frames: number, beats: number[] = [], fps = 30) =>
  beats.length >= count
    ? Math.max(4, Math.round(beats[beats.length - count + index] * fps) - 3)
    : Math.round(8 + (index * Math.max(0, frames * 0.7 - 8)) / Math.max(1, count));
