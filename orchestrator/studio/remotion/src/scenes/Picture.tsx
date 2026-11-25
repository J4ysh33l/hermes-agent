import React from "react";
import {AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame} from "remotion";
import {Arrive} from "../motion";
import {SAFE, useTheme} from "../theme";
import type {ImageScene} from "../types";

const VIDEO = /\.(mp4|mov|webm|mkv)$/i;

// Full-bleed image or clip with a slow Ken Burns push, a dark gradient and the caption on a tilted card.
export const Picture: React.FC<{scene: ImageScene; frames: number}> = ({scene, frames}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, frames], [1.0, 1.12]);
  const src = /^https?:/.test(scene.src) ? scene.src : staticFile(scene.src);
  const media = {width: "100%", height: "100%", objectFit: "cover" as const, transform: `scale(${zoom})`};
  return (
    <AbsoluteFill>
      {VIDEO.test(scene.src) ? <OffthreadVideo src={src} muted style={media} /> : <Img src={src} style={media} />}
      <AbsoluteFill style={{background: `linear-gradient(180deg, ${theme.bg}40 0%, ${theme.bg}1a 40%, ${theme.bg}e6 100%)`}} />
      {scene.caption ? (
        <AbsoluteFill style={{justifyContent: "flex-start", alignItems: "flex-start", padding: `${SAFE.top}px ${SAFE.side}px`}}>
          <Arrive delay={6} enter="drop" style={{fontFamily: theme.sans, fontWeight: 900, fontSize: 70,
            color: theme.bg, background: theme.accent, padding: "16px 28px", borderRadius: 16, lineHeight: 1.1,
            rotate: "-2deg"}}>
            {scene.caption}
          </Arrive>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};
