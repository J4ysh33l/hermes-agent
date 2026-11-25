import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {usePop} from "studio/motion";
import {useTheme} from "studio/theme";
import type {CustomScene} from "studio/types";

// Two progress lanes race: the slow one crawls, the fast one finishes on the second sentence and its
// multiplier lands with a pop. Written by hand as a custom-scene test (as Claude would write one).
export default function Scene({scene, frames}: {scene: CustomScene; frames: number}) {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {slow, fast, times} = scene.props as {slow: string; fast: string; times: number};
  const second = Math.round((scene.beats[1] ?? frames / 60) * 30);
  const race = interpolate(frame, [6, Math.max(12, second)], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic)});
  const pop = usePop(second);
  const lane = (label: string, share: number, colour: string, done: boolean) => (
    <div style={{display: "flex", flexDirection: "column", gap: 18}}>
      <div style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 56, color: theme.text}}>{label}</div>
      <div style={{height: 70, borderRadius: 35, background: theme.panel, overflow: "hidden", border: `3px solid ${theme.muted}44`}}>
        <div style={{height: "100%", width: `${Math.max(4, share * 100)}%`, borderRadius: 35, background: colour,
          boxShadow: done ? `0 0 40px ${colour}` : "none"}} />
      </div>
    </div>
  );
  return (
    <div style={{display: "flex", flexDirection: "column", gap: 70}}>
      {lane(slow, race / times, theme.muted, false)}
      {lane(fast, race, theme.accent, race >= 1)}
      <div style={{alignSelf: "center", fontFamily: theme.sans, fontWeight: 900, fontSize: 200, color: theme.accent,
        transform: `scale(${pop})`, opacity: Math.min(1, pop * 2), textShadow: `0 0 60px ${theme.accent}66`}}>
        {times}×
      </div>
    </div>
  );
}
