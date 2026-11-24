import React from "react";
import {Arrive, revealAt} from "../motion";
import {useTheme} from "../theme";
import type {CompareScene, Side} from "../types";

// Two stacked cards (a vertical video has no room side by side) with a VS badge between them.
export const Compare: React.FC<{scene: CompareScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const count = scene.left.points.length + scene.right.points.length;
  const card = (side: Side, colour: string, first: number, delay: number) => (
    <Arrive delay={delay} enter="slide" style={{background: theme.panel, borderRadius: 26, padding: 40,
      border: `4px solid ${colour}`}}>
      <div style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 66, color: colour, marginBottom: 18}}>
        {side.label}
      </div>
      {side.points.map((point, n) => (
        <Arrive key={n} delay={revealAt(first + n, count, frames, scene.beats)} enter="rise"
          style={{fontFamily: theme.sans, fontWeight: 600, fontSize: 48, color: theme.text, lineHeight: 1.3}}>
          • {point}
        </Arrive>
      ))}
    </Arrive>
  );
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "stretch"}}>
      {card(scene.left, theme.bad, 0, 0)}
      <Arrive delay={8} enter="pop" style={{alignSelf: "center", margin: "-26px 0", zIndex: 2,
        fontFamily: theme.sans, fontWeight: 900, fontSize: 54, color: theme.bg, background: theme.accent,
        borderRadius: 60, padding: "14px 34px"}}>
        VS
      </Arrive>
      {card(scene.right, theme.good, scene.left.points.length, 4)}
    </div>
  );
};
