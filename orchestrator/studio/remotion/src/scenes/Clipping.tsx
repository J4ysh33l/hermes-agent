import React from "react";
import {Easing, interpolate, useCurrentFrame} from "remotion";
import {Arrive} from "../motion";
import {useTheme} from "../theme";
import type {ClippingScene} from "../types";

// A newspaper clipping (rebuilt as text, never a screenshot) tilts in; a highlighter sweeps over the key words.
export const Clipping: React.FC<{scene: ClippingScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const at = scene.highlight ? scene.headline.toLowerCase().indexOf(scene.highlight.toLowerCase()) : -1;
  const sweep = interpolate(frame, [14, Math.min(34, frames * 0.6)], [0, 100], {extrapolateLeft: "clamp",
    extrapolateRight: "clamp", easing: Easing.out(Easing.cubic)});
  const before = at >= 0 ? scene.headline.slice(0, at) : scene.headline;
  const marked = at >= 0 ? scene.headline.slice(at, at + scene.highlight.length) : "";
  const after = at >= 0 ? scene.headline.slice(at + scene.highlight.length) : "";
  return (
    <Arrive enter="drop" style={{background: "#f4efe4", color: "#161412", padding: "46px 50px 56px", rotate: "-1.5deg",
      boxShadow: "0 30px 90px rgba(0,0,0,0.45)", clipPath: "polygon(0 1%, 4% 0, 30% 1.5%, 62% 0, 100% 1%, 99% 98%, 70% 100%, 35% 98.5%, 2% 100%)"}}>
      <div style={{display: "flex", justifyContent: "space-between", fontFamily: "Georgia, serif", fontSize: 30,
        textTransform: "uppercase", letterSpacing: 4, borderBottom: "3px solid #161412", paddingBottom: 14,
        marginBottom: 30}}>
        <span>{scene.source}</span><span>{scene.date}</span>
      </div>
      <div style={{fontFamily: "Georgia, 'Times New Roman', serif", fontWeight: 700, fontSize: scene.headline.length > 70 ? 64 : 78,
        lineHeight: 1.12}}>
        {before}
        {marked ? (
          <span style={{backgroundImage: `linear-gradient(${theme.accent}99, ${theme.accent}99)`, backgroundRepeat: "no-repeat",
            backgroundSize: `${sweep}% 80%`, backgroundPosition: "0 70%", padding: "0 4px"}}>{marked}</span>
        ) : null}
        {after}
      </div>
    </Arrive>
  );
};
