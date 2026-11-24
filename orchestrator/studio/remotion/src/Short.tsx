import React from "react";
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {Captions} from "./Captions";
import {Emoji} from "./Emoji";
import {Camera, SceneFrame} from "./motion";
import {Bullets} from "./scenes/Bullets";
import {Code} from "./scenes/Code";
import {Compare} from "./scenes/Compare";
import {Picture} from "./scenes/Picture";
import {Stat} from "./scenes/Stat";
import {BeforeAfter} from "./scenes/BeforeAfter";
import {Chart} from "./scenes/Chart";
import {Clipping} from "./scenes/Clipping";
import {Diagram} from "./scenes/Diagram";
import {Logo} from "./scenes/Logo";
import {WorldMap} from "./scenes/Map";
import {Meme} from "./scenes/Meme";
import {Post} from "./scenes/Post";
import {Quote} from "./scenes/Quote";
import {Terminal} from "./scenes/Terminal";
import {Timeline} from "./scenes/Timeline";
import {Title} from "./scenes/Title";
import {ProfileProvider, Theme, useTheme} from "./theme";
import type {Scene, ShortProps} from "./types";

type SceneView = React.FC<{scene: never; frames: number}>;

// Scene type → component, and whether it fills the screen itself (no safe-area padding).
export const SCENES: Record<Scene["type"], {view: SceneView; fullBleed: boolean}> = {
  title: {view: Title as SceneView, fullBleed: false},
  bullets: {view: Bullets as SceneView, fullBleed: false},
  code: {view: Code as SceneView, fullBleed: false},
  stat: {view: Stat as SceneView, fullBleed: false},
  image: {view: Picture as SceneView, fullBleed: true},
  compare: {view: Compare as SceneView, fullBleed: false},
  terminal: {view: Terminal as SceneView, fullBleed: false},
  chart: {view: Chart as SceneView, fullBleed: false},
  diagram: {view: Diagram as SceneView, fullBleed: false},
  quote: {view: Quote as SceneView, fullBleed: false},
  timeline: {view: Timeline as SceneView, fullBleed: false},
  clipping: {view: Clipping as SceneView, fullBleed: false},
  post: {view: Post as SceneView, fullBleed: false},
  meme: {view: Meme as SceneView, fullBleed: false},
  beforeafter: {view: BeforeAfter as SceneView, fullBleed: false},
  logo: {view: Logo as SceneView, fullBleed: false},
  map: {view: WorldMap as SceneView, fullBleed: false},
};

const GRID = "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)";

// The background never sits still: a glow drifting, optionally a grid scrolling under it.
export const BACKGROUNDS: Record<Theme["background"], React.FC> = {
  "glow-grid": () => {
    const frame = useCurrentFrame();
    return (
      <>
        <Glow />
        <AbsoluteFill style={{opacity: 0.07, backgroundImage: GRID, backgroundSize: "90px 90px",
          transform: `translateY(${(frame * 0.6) % 90}px)`}} />
      </>
    );
  },
  glow: () => <Glow />,
  flat: () => null,
};

const Glow: React.FC = () => {
  const frame = useCurrentFrame();
  const theme = useTheme();
  const x = 50 + 30 * Math.sin(frame / 90);
  const y = 35 + 20 * Math.cos(frame / 120);
  return <AbsoluteFill style={{background: `radial-gradient(circle at ${x}% ${y}%, ${theme.glow} 0%, ${theme.bg} 60%)`}} />;
};

const Progress: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const theme = useTheme();
  return <div style={{position: "absolute", top: 0, left: 0, height: 12, background: theme.accent,
    width: `${interpolate(frame, [0, durationInFrames], [0, 100])}%`}} />;
};

// The emoji lands on the scene's first emphasised word, else just after the scene starts (frames from its start).
const emojiAt = (scene: Scene, words: ShortProps["words"], fps: number) => {
  const hit = words.find((w) => w.emphasis && w.start >= scene.start && w.start < scene.end);
  return Math.round(((hit ? hit.start : scene.start + 0.3) - scene.start) * fps);
};

const Body: React.FC<ShortProps> = ({audio, scenes, words}) => {
  const {fps, durationInFrames} = useVideoConfig();
  const theme = useTheme();
  const Background = BACKGROUNDS[theme.background];
  return (
    <AbsoluteFill style={{background: theme.bg}}>
      <Background />
      <Camera hits={words.filter((w) => w.emphasis).map((w) => w.start)}>
        {scenes.map((scene, n) => {
          const from = Math.round(scene.start * fps);
          // the last scene holds to the end of the video (no empty tail after the last word)
          const until = n + 1 < scenes.length ? Math.round(scenes[n + 1].start * fps) : durationInFrames;
          const frames = Math.max(1, until - from);
          const {view: View, fullBleed} = SCENES[scene.type];
          return (
            <Sequence key={n} from={from} durationInFrames={frames} layout="none">
              <SceneFrame frames={frames} enter={scene.enter || undefined} exit={scene.exit || undefined}
                fullBleed={fullBleed}>
                <View scene={scene as never} frames={frames} />
              </SceneFrame>
              {scene.emoji ? <Emoji char={scene.emoji} at={emojiAt(scene, words, fps)} /> : null}
            </Sequence>
          );
        })}
      </Camera>
      <Captions words={words} />
      <Progress />
      {audio ? <Audio src={staticFile(audio)} /> : null}
    </AbsoluteFill>
  );
};

export const Short: React.FC<ShortProps> = (props) => (
  <ProfileProvider profile={props.profile}>
    <Body {...props} />
  </ProfileProvider>
);
