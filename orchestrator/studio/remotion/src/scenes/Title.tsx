import React from "react";
import {interpolate} from "remotion";
import {usePop} from "../motion";
import {theme} from "../theme";
import type {TitleScene} from "../types";

// Big punch line, words landing one after another; the kicker is a small tag above it.
export const Title: React.FC<{scene: TitleScene; frames: number}> = ({scene}) => {
  const tag = usePop(0);
  const words = scene.text.split(/\s+/).filter(Boolean);
  const size = words.join(" ").length > 40 ? 96 : 124;
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 36}}>
      {scene.kicker ? (
        <div
          style={{
            fontFamily: theme.mono, fontSize: 40, color: theme.bg, background: theme.accent,
            padding: "10px 22px", borderRadius: 10, transform: `scale(${tag})`, transformOrigin: "left center",
          }}
        >
          {scene.kicker}
        </div>
      ) : null}
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: size, lineHeight: 1.05, color: theme.text}}>
        {words.map((word, n) => (
          <Landing key={n} delay={3 + n * 3} last={n === words.length - 1}>
            {word}
          </Landing>
        ))}
      </div>
    </div>
  );
};

const Landing: React.FC<{delay: number; last: boolean; children: React.ReactNode}> = ({delay, last, children}) => {
  const p = usePop(delay);
  return (
    <span
      style={{
        display: "inline-block", marginRight: 26, color: last ? theme.accent : theme.text,
        transform: `translateY(${interpolate(p, [0, 1], [60, 0])}px) scale(${interpolate(p, [0, 1], [0.7, 1])})`,
        opacity: Math.min(1, p * 2),
      }}
    >
      {children}
    </span>
  );
};
