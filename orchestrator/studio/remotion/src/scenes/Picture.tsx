import React from "react";
import {AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from "remotion";
import {usePop} from "../motion";
import {theme} from "../theme";
import type {ImageScene} from "../types";

const VIDEO = /\.(mp4|mov|webm|mkv)$/i;

// Full-bleed image or clip with a slow Ken Burns push, a dark gradient and the caption on a card.
// Rendered outside SceneFrame's padding: it fills the screen.
export const Picture: React.FC<{scene: ImageScene; frames: number}> = ({scene, frames}) => {
  const frame = useCurrentFrame();
  const card = usePop(6);
  const zoom = interpolate(frame, [0, frames], [1.0, 1.12]);
  const src = /^https?:/.test(scene.src) ? scene.src : staticFile(scene.src);
  const media = {width: "100%", height: "100%", objectFit: "cover" as const, transform: `scale(${zoom})`};
  return (
    <AbsoluteFill>
      {VIDEO.test(scene.src) ? <OffthreadVideo src={src} muted style={media} /> : <Img src={src} style={media} />}
      <AbsoluteFill style={{background: "linear-gradient(180deg, rgba(11,15,25,0.25) 0%, rgba(11,15,25,0.1) 40%, rgba(11,15,25,0.9) 100%)"}} />
      {scene.caption ? (
        <AbsoluteFill style={{justifyContent: "flex-start", padding: `${theme.safeTop}px ${theme.side}px`}}>
          <div style={{alignSelf: "flex-start", fontFamily: theme.sans, fontWeight: 900, fontSize: 70, color: theme.bg,
            background: theme.accent, padding: "16px 28px", borderRadius: 16, lineHeight: 1.1,
            transform: `rotate(-2deg) scale(${card})`, transformOrigin: "left top"}}>
            {scene.caption}
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};
