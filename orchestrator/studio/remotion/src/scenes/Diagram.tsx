import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {Arrive, revealAt} from "../motion";
import {useTheme} from "../theme";
import type {DiagramScene} from "../types";

const ARROW = 110;

// A flow, top to bottom: each box arrives on its sentence and the arrow into it draws itself first.
export const Diagram: React.FC<{scene: DiagramScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const n = scene.nodes.length;
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center"}}>
      {scene.title ? (
        <Arrive style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 80, color: theme.text, marginBottom: 44,
          alignSelf: "flex-start"}}>{scene.title}</Arrive>
      ) : null}
      {scene.nodes.map((node, i) => {
        const at = revealAt(i, n, frames, scene.beats);
        const colour = [theme.accent, theme.cool, theme.good, theme.bad][i % 4];
        const draw = interpolate(frame, [at - 8, at], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        return (
          <React.Fragment key={i}>
            {i > 0 ? (
              <svg width={60} height={ARROW}>
                <line x1={30} y1={4} x2={30} y2={ARROW - 18} stroke={theme.muted} strokeWidth={8} strokeLinecap="round"
                  strokeDasharray={ARROW} strokeDashoffset={ARROW * (1 - draw)} />
                <path d={`M12 ${ARROW - 30} L30 ${ARROW - 6} L48 ${ARROW - 30}`} fill="none" stroke={theme.muted}
                  strokeWidth={8} strokeLinecap="round" strokeLinejoin="round" opacity={draw >= 1 ? 1 : 0} />
              </svg>
            ) : null}
            <Arrive delay={at} enter="pop" style={{background: theme.panel, border: `5px solid ${colour}`,
              borderRadius: 30, padding: "34px 56px", minWidth: 640, textAlign: "center", fontFamily: theme.sans,
              fontWeight: 800, fontSize: n > 4 ? 54 : 66, color: theme.text, boxShadow: `0 0 50px ${colour}33`}}>
              {node}
            </Arrive>
          </React.Fragment>
        );
      })}
    </div>
  );
};
