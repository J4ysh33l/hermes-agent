import React from "react";
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {Captions} from "./Captions";
import {SceneFrame} from "./motion";
import {Bullets} from "./scenes/Bullets";
import {Code} from "./scenes/Code";
import {Compare} from "./scenes/Compare";
import {Picture} from "./scenes/Picture";
import {Stat} from "./scenes/Stat";
import {Title} from "./scenes/Title";
import {theme} from "./theme";
import type {Scene, ShortProps} from "./types";

type SceneView = React.FC<{scene: never; frames: number}>;

// Scene type → component, and whether it fills the screen itself (no padded, punched-in frame).
const SCENES: Record<Scene["type"], {view: SceneView; fullBleed: boolean}> = {
  title: {view: Title as SceneView, fullBleed: false},
  bullets: {view: Bullets as SceneView, fullBleed: false},
  code: {view: Code as SceneView, fullBleed: false},
  stat: {view: Stat as SceneView, fullBleed: false},
  image: {view: Picture as SceneView, fullBleed: true},
  compare: {view: Compare as SceneView, fullBleed: false},
};

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const x = 50 + 30 * Math.sin(frame / 90);
  const y = 35 + 20 * Math.cos(frame / 120);
  return (
    <AbsoluteFill style={{background: `radial-gradient(circle at ${x}% ${y}%, ${theme.bgGlow} 0%, ${theme.bg} 60%)`}}>
      <AbsoluteFill style={{opacity: 0.07, backgroundImage:
        "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)",
        backgroundSize: "90px 90px", transform: `translateY(${(frame * 0.6) % 90}px)`}} />
    </AbsoluteFill>
  );
};

const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  return (
    <div style={{position: "absolute", top: 0, left: 0, height: 12, background: theme.accent,
      width: `${interpolate(frame, [0, durationInFrames], [0, 100])}%`}} />
  );
};

export const Short: React.FC<ShortProps> = ({audio, scenes, words}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: theme.bg}}>
      <Background />
      {scenes.map((scene, n) => {
        const from = Math.round(scene.start * fps);
        const until = n + 1 < scenes.length ? Math.round(scenes[n + 1].start * fps) : Math.round(scene.end * fps);
        const frames = Math.max(1, until - from);
        const {view: View, fullBleed} = SCENES[scene.type];
        const body = <View scene={scene as never} frames={frames} />;
        return (
          <Sequence key={n} from={from} durationInFrames={frames} layout="none">
            {fullBleed ? body : <SceneFrame frames={frames}>{body}</SceneFrame>}
          </Sequence>
        );
      })}
      <Captions words={words} />
      <Progress />
      {audio ? <Audio src={staticFile(audio)} /> : null}
    </AbsoluteFill>
  );
};
