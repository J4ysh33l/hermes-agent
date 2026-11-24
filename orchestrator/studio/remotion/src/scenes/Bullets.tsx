import React from "react";
import {Arrive, revealAt} from "../motion";
import {useTheme} from "../theme";
import type {BulletsScene} from "../types";

// Numbered list; each item arrives on the sentence that says it.
export const Bullets: React.FC<{scene: BulletsScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  return (
    <div style={{display: "flex", flexDirection: "column", gap: 34}}>
      {scene.title ? (
        <Arrive style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 84, color: theme.text, marginBottom: 20}}>
          {scene.title}
        </Arrive>
      ) : null}
      {scene.items.map((item, n) => {
        const colour = n % 2 ? theme.cool : theme.accent;
        return (
          <Arrive key={n} delay={revealAt(n, scene.items.length, frames, scene.beats)} enter="slide"
            style={{display: "flex", alignItems: "center", gap: 30, background: theme.panel, borderRadius: 22,
              padding: "28px 34px", borderLeft: `10px solid ${colour}`}}>
            <div style={{fontFamily: theme.monoFamily, fontSize: 52, color: colour}}>{n + 1}</div>
            <div style={{fontFamily: theme.sans, fontWeight: 800, fontSize: 56, color: theme.text, lineHeight: 1.15}}>
              {item}
            </div>
          </Arrive>
        );
      })}
    </div>
  );
};
