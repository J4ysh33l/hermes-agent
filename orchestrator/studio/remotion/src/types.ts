import type {Enter, Exit, Profile} from "./theme";

// The props video.py writes (props.json). Times are seconds on the voice track; the composition is
// as long as the voice plus a short tail. Every file path is relative to the job folder (--public-dir).

export interface Word {
  text: string;
  start: number;
  end: number;
  emphasis: boolean; // *marked* in the script: accent colour + camera punch
}

export interface Side {
  label: string;
  points: string[];
}

interface SceneBase {
  start: number;
  end: number;
  beats: number[]; // each sentence's start, seconds from the scene's start
  enter: Enter | ""; // "" = the profile's
  exit: Exit | "";
}

export interface TitleScene extends SceneBase {
  type: "title";
  text: string;
  kicker: string;
}

export interface BulletsScene extends SceneBase {
  type: "bullets";
  title: string;
  items: string[];
}

export interface CodeScene extends SceneBase {
  type: "code";
  title: string;
  code: string;
}

export interface StatScene extends SceneBase {
  type: "stat";
  value: number;
  prefix: string;
  suffix: string;
  label: string;
}

export interface ImageScene extends SceneBase {
  type: "image";
  src: string;
  caption: string;
}

export interface CompareScene extends SceneBase {
  type: "compare";
  left: Side;
  right: Side;
}

export type Scene = TitleScene | BulletsScene | CodeScene | StatScene | ImageScene | CompareScene;

export interface ShortProps extends Record<string, unknown> {
  profile: Profile;
  audio: string;
  seconds: number;
  scenes: Scene[];
  words: Word[];
}
