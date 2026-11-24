import React from "react";
import {Composition} from "remotion";
import {Cover, Probe} from "./Cover";
import {Short} from "./Short";
import {DEFAULT_PROFILE, FPS, HEIGHT, WIDTH} from "./theme";
import type {CoverProps, ProbeProps, ShortProps} from "./types";

const preview: ShortProps = {
  profile: DEFAULT_PROFILE,
  audio: "",
  seconds: 4,
  words: [],
  scenes: [{type: "title", start: 0, end: 4, beats: [0], enter: "", exit: "", emoji: "", text: "Open props.json in a job folder", kicker: "studio"}],
};

const coverPreview: CoverProps = {profile: DEFAULT_PROFILE, scene: preview.scenes[0], words: "Cover words here"};

const probePreview: ProbeProps = {profile: DEFAULT_PROFILE, scene: preview.scenes[0], frames: FPS * 4};

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
  </>
);
