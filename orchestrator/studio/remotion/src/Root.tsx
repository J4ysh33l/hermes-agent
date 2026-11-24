import React from "react";
import {Composition} from "remotion";
import {Short} from "./Short";
import {FPS, HEIGHT, WIDTH} from "./theme";
import type {ShortProps} from "./types";

const preview: ShortProps = {
  audio: "",
  seconds: 4,
  words: [],
  scenes: [{type: "title", start: 0, end: 4, beats: [0], text: "Open props.json in a job folder", kicker: "studio"}],
};

export const RemotionRoot: React.FC = () => (
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
);
