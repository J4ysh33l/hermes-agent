import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {Arrive, revealAt} from "../motion";
import {useTheme} from "../theme";
import type {TimelineScene} from "../types";

const ROW = 230;

// A vertical line draws down; each event's dot pops and its text slides in as the line reaches it.
export const Timeline: React.FC<{scene: TimelineScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const n = scene.events.length;
  const times = scene.events.map((_, i) => revealAt(i, n, frames, scene.beats));
  const reach = interpolate(frame, [times[0] - 6, times[n - 1]], [0, (n - 1) * ROW], {extrapolateLeft: "clamp",
    extrapolateRight: "clamp"});
  return (
    <div>
      {scene.title ? (
        <Arrive style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 80, color: theme.text, marginBottom: 56}}>
          {scene.title}
        </Arrive>
      ) : null}
      <div style={{position: "relative", height: (n - 1) * ROW + 120}}>
        <div style={{position: "absolute", left: 28, top: 30, width: 8, height: (n - 1) * ROW + 8,
          background: `${theme.muted}33`, borderRadius: 4}} />
        <div style={{position: "absolute", left: 28, top: 30, width: 8, height: reach, background: theme.accent,
          borderRadius: 4}} />
        {scene.events.map((event, i) => (
          <div key={i} style={{position: "absolute", top: i * ROW, left: 0, display: "flex", alignItems: "flex-start",
            gap: 40}}>
            <Arrive delay={times[i]} enter="pop" style={{width: 64, height: 64, borderRadius: 32, background: theme.bg,
              border: `8px solid ${theme.accent}`, boxSizing: "border-box", flexShrink: 0}}>{" "}</Arrive>
            <Arrive delay={times[i] + 2} enter="slide">
              <div style={{fontFamily: theme.monoFamily, fontSize: 48, color: theme.accent}}>{event.when}</div>
              <div style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 62, color: theme.text, lineHeight: 1.15,
                maxWidth: 760}}>{event.what}</div>
            </Arrive>
          </div>
        ))}
      </div>
    </div>
  );
};
