import React from "react";
import {Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Arrive, usePop} from "../motion";
import {useTheme} from "../theme";
import type {LogoScene} from "../types";

// The subject, big, as it is named (Fireship's opener): logo (or its initial) scales in inside a
// pulsing ring, the name and tagline follow.
export const Logo: React.FC<{scene: LogoScene; frames: number}> = ({scene}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const p = usePop(0);
  const ring = 1 + 0.06 * Math.sin(frame / 7);
  const src = !scene.src ? "" : /^https?:/.test(scene.src) ? scene.src : staticFile(scene.src);
  return (
    <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 50}}>
      <div style={{width: 440, height: 440, borderRadius: 220, display: "flex", alignItems: "center",
        justifyContent: "center", background: theme.panel, border: `10px solid ${theme.accent}`,
        boxShadow: `0 0 ${120 * ring}px ${theme.accent}66`, transform: `scale(${interpolate(p, [0, 1], [0.3, 1]) * ring})`,
        rotate: `${interpolate(p, [0, 1], [-90, 0])}deg`}}>
        {src ? <Img src={src} style={{width: 280, height: 280, objectFit: "contain"}} />
          : <span style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 220, color: theme.accent}}>
            {scene.name.slice(0, 1).toUpperCase()}</span>}
      </div>
      <Arrive delay={8} enter="rise" style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 120, color: theme.text,
        textAlign: "center", lineHeight: 1}}>{scene.name}</Arrive>
      {scene.tagline ? (
        <Arrive delay={14} enter="fade" style={{fontFamily: theme.sans, fontWeight: 700, fontSize: 52,
          color: theme.muted, textAlign: "center"}}>{scene.tagline}</Arrive>
      ) : null}
    </div>
  );
};
