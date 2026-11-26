import React from "react";
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {EMOJI_BAND, FEELS} from "./motion";
import {SAFE, useProfile} from "./theme";

const SPARKS = 8;
const SIZE = 180;

// One big emoji pops in at the upper right of the safe area, wobbles, and throws small copies up and out
// that fade. It stays inside the band SceneFrame keeps free above the scene (EMOJI_BAND), so it never lands
// on the scene's words; its copies fly upward and sideways, never down into the scene.
export const Emoji: React.FC<{char: string; at: number}> = ({char, at}) => {
  const frame = useCurrentFrame() - at;
  const {fps} = useVideoConfig();
  const {motion} = useProfile();
  if (frame < 0) return null;
  const pop = spring({frame, fps, config: FEELS.bouncy});
  const fade = interpolate(frame, [fps * 1.6, fps * 2], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const burst = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: "clamp"});
  const tilt = motion.feel === "soft" ? 0 : 10 * Math.sin(frame / 4) * (1 - burst * 0.6);
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      <div style={{position: "absolute", right: SAFE.side + 30, top: SAFE.top + (EMOJI_BAND - SIZE * 1.15) / 2, fontSize: SIZE, transform: `scale(${pop}) rotate(${tilt}deg)`,
        opacity: fade, filter: "drop-shadow(0 18px 30px rgba(0,0,0,0.35))"}}>
        {char}
        {Array.from({length: SPARKS}, (_, i) => {
          const angle = Math.PI + (i / (SPARKS - 1)) * Math.PI + (random(`${char}${i}`) - 0.5) * 0.3; // the upper half
          const reach = 110 + 70 * random(`${char}r${i}`);
          return (
            <span key={i} style={{position: "absolute", left: 50, top: 60, fontSize: 64, opacity: 1 - burst,
              transform: `translate(${Math.cos(angle) * reach * burst}px, ${Math.sin(angle) * reach * burst}px)`}}>
              {char}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
