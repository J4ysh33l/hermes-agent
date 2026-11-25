import React from "react";
import {AbsoluteFill, interpolate, random, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {FEELS} from "./motion";
import {useProfile} from "./theme";

const SPARKS = 8;

// One big emoji pops in upper right, wobbles, and throws a ring of small copies outward that fade.
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
      <div style={{position: "absolute", right: 120, top: 330, fontSize: 200, transform: `scale(${pop}) rotate(${tilt}deg)`,
        opacity: fade, filter: "drop-shadow(0 18px 30px rgba(0,0,0,0.35))"}}>
        {char}
        {Array.from({length: SPARKS}, (_, i) => {
          const angle = (i / SPARKS) * Math.PI * 2 + random(`${char}${i}`) * 0.6;
          const reach = 170 + 90 * random(`${char}r${i}`);
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
