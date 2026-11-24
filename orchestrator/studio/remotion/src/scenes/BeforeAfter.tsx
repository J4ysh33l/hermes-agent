import React from "react";
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Arrive, revealAt} from "../motion";
import {useTheme} from "../theme";
import type {BeforeAfterScene, Panel} from "../types";

// "Before" fills the card; a wipe slides "after" across it when the narration gets there.
export const BeforeAfter: React.FC<{scene: BeforeAfterScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const at = revealAt(1, 2, frames, scene.beats);
  const wipe = interpolate(frame, [at - 4, at + 10], [0, 100], {extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic)});
  return (
    <Arrive enter="rise" style={{position: "relative", height: 1000, borderRadius: 30, overflow: "hidden",
      boxShadow: "0 40px 120px rgba(0,0,0,0.45)"}}>
      <Side panel={scene.before} colour={theme.bad} tag="BEFORE" />
      <AbsoluteFill style={{clipPath: `inset(0 ${100 - wipe}% 0 0)`}}>
        <Side panel={scene.after} colour={theme.good} tag="AFTER" />
      </AbsoluteFill>
      <div style={{position: "absolute", top: 0, bottom: 0, left: `${wipe}%`, width: 10, marginLeft: -5,
        background: theme.accent, opacity: wipe > 0 && wipe < 100 ? 1 : 0}} />
    </Arrive>
  );
};

const Side: React.FC<{panel: Panel; colour: string; tag: string}> = ({panel, colour, tag}) => {
  const theme = useTheme();
  const src = !panel.src ? "" : /^https?:/.test(panel.src) ? panel.src : staticFile(panel.src);
  return (
    <AbsoluteFill style={{background: src ? "#000" : theme.panel, alignItems: "center", justifyContent: "center"}}>
      {src ? <Img src={src} style={{position: "absolute", width: "100%", height: "100%", objectFit: "cover"}} /> : null}
      <div style={{position: "absolute", top: 34, left: 34, fontFamily: theme.monoFamily, fontSize: 34, color: theme.bg,
        background: colour, padding: "8px 18px", borderRadius: 10}}>{tag}</div>
      <div style={{position: "relative", fontFamily: theme.sans, fontWeight: 900, fontSize: 84, color: src ? "#fff" : colour,
        textAlign: "center", padding: 40, textShadow: src ? "0 6px 30px rgba(0,0,0,0.8)" : "none",
        alignSelf: src ? "flex-end" : "center", marginTop: src ? "auto" : 0}}>{panel.label}</div>
    </AbsoluteFill>
  );
};
