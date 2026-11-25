import React from "react";
import {Composition} from "remotion";
import {Cover, Probe} from "./Cover";
import {Short} from "./Short";
import {Graphic} from "./edit/Graphic";
import type {GraphicProps} from "./edit/Graphic";
import {Timeline} from "./edit/Timeline";
import type {TimelineProps} from "./edit/Timeline";
import {DEFAULT_PROFILE, FPS, HEIGHT, WIDTH} from "./theme";
import type {CoverProps, ProbeProps, ShortProps} from "./types";

const preview: ShortProps = {
  profile: DEFAULT_PROFILE,
  audio: "",
  seconds: 4,
  words: [],
  scenes: [{type: "title", start: 0, end: 4, beats: [0], enter: "", exit: "", transition: "", emoji: "", text: "Open props.json in a job folder", kicker: "studio"}],
};

const coverPreview: CoverProps = {profile: DEFAULT_PROFILE, scene: preview.scenes[0], words: "Cover words here"};

const probePreview: ProbeProps = {profile: DEFAULT_PROFILE, scene: preview.scenes[0], frames: FPS * 4};

const timelinePreview: TimelineProps = {
  look: {font: "intertight", serif: "intertight", ink: "#2A4755", paper: "#FAFAF7", accent: "#41C1BA", alert: "#E5484D",
    good: "#2FA39C", box_bg: "#2A4755", box_fg: "#FFFFFF", figure: "#41C1BA", radius: 14, handle: "@medochealth.in",
    title: {kind: "card", font: "intertight", bg: "#FAFAF7", fg: "#2A4755", size: 66, y: 0.09, subtitle: false, weight: 600, accent: "#2FA39C"}},
  captions: {font: "poppins", size: 58, case: "lower", colour: "#FFFFFF", active: "#41C1BA", mode: "box", box_text: "#10302F",
    shadow: 3, y: 0.62, problem: "#E5484D", solution: "#41C1BA"},
  items: [{kind: "scene", type: "statement", layout: "panel", text: "the price", strike_at: 30, from: 0, frames: 90}],
  pages: [{from: 0, to: 45, place: "seam", words: [{text: "the", from: 0, to: 15}, {text: "price", from: 15, to: 45}]}],
  frames: 90,
};

const graphicPreview: GraphicProps = {
  look: {font: "manrope", serif: "newsreader", ink: "#111111", paper: "#FFFFFF", accent: "#FFD400", alert: "#E53935",
    good: "#2ECC71", box_bg: "#000000", box_fg: "#FFFFFF", figure: "none", radius: 10,
    title: {kind: "card", font: "newsreader", bg: "#FFFFFF", fg: "#000000", size: 56, y: 0.07, subtitle: false,
      weight: 500, accent: "none"}},
  item: {kind: "stat", text: "Same questions, 10×", sub: "beats one more mock"},
  frames: FPS * 3,
};

export const COVER_FRAMES = FPS * 4; // the still is the last frame: every scene has arrived by then

export const RemotionRoot: React.FC = () => (
  <>
  <Composition
    id="Short"
    component={Short}
    width={WIDTH}
    height={HEIGHT}
    fps={FPS}
    durationInFrames={FPS * 4}
    defaultProps={preview}
    calculateMetadata={({props}) => ({durationInFrames: Math.max(1, Math.ceil(props.seconds * FPS))})}
  />
  <Composition id="Cover" component={Cover} width={WIDTH} height={HEIGHT} fps={FPS} durationInFrames={COVER_FRAMES}
    defaultProps={coverPreview} />
  <Composition id="Probe" component={Probe} width={WIDTH} height={HEIGHT} fps={FPS} durationInFrames={COVER_FRAMES}
    defaultProps={probePreview} calculateMetadata={({props}) => ({durationInFrames: Math.max(1, props.frames)})} />
  <Composition id="EditGraphic" component={Graphic} width={WIDTH} height={HEIGHT} fps={FPS} durationInFrames={FPS * 3}
    defaultProps={graphicPreview} calculateMetadata={({props}) => ({durationInFrames: Math.max(1, props.frames)})} />
  <Composition id="EditTimeline" component={Timeline} width={WIDTH} height={HEIGHT} fps={FPS} durationInFrames={FPS * 3}
    defaultProps={timelinePreview} calculateMetadata={({props}) => ({durationInFrames: Math.max(1, props.frames)})} />
  </>
);
